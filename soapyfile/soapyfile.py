#!/usr/bin/python3

import os, sys, time
import argparse
import numpy as np
from struct import pack, calcsize
from queue import Queue
from threading import Thread, Event, Lock
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn


def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-l', '--list', action='store_true', help='list available device names')
    parser.add_argument('-d', '--device', help='device name')
    parser.add_argument('-f', '--frequency', type=float, help='center frequency (Hz)')
    parser.add_argument('-r', '--rate', type=float, help='sampling rate (Hz)')
    parser.add_argument('-g', '--gain', type=float, help='front end gain (dB)')
    parser.add_argument('-a', '--agc', action='store_true', help='enable AGC')
    parser.add_argument('--iq-swap', action='store_true', help='swap IQ signals')
    parser.add_argument('--biastee', action='store_true', help='enable bias tee')
    parser.add_argument('--digital-agc', action='store_true', help='enable digital AGC')
    parser.add_argument('--offset-tune', action='store_true', help='enable offset tune')
    parser.add_argument('--direct-samp', type=int, help='select I or Q channel: 1 or 2')

    # options
    parser.add_argument('--pcm16', action='store_true', help='write 16-bit PCM samples')
    parser.add_argument('--rf64', action='store_true', help='write RF64 file')
    parser.add_argument('--notimestamp', action='store_true', help='do not append timestamp to output file name')
    parser.add_argument('--pause', action='store_true', help='pause recording')
    parser.add_argument('--output', default='output', help='output file name')
    parser.add_argument('--packet-size', default=1024, type=int, help='packet size in bytes')
    parser.add_argument('--buffer-size', default=256, type=int, help='buffer size in MB')

    # rest server and peak meter
    parser.add_argument('--hostname', default='0.0.0.0', help='REST server hostname')
    parser.add_argument('--port', default=8080, type=int, help='REST server port number')
    parser.add_argument('--refresh', default=2, type=float, help='peak meter refresh (sec)')
    parser.add_argument('--quiet', action='store_true', help='do not print peak values')
    return parser.parse_args()


# utilities

def afloat(text):
    try:
        return float(text) 
    except ValueError:
        pass


def abool(text):
    text = text.strip().lower()
    if text == 'y' or text == 'yes' or text == 'true':
        return True
    if text == 'n' or text == 'no' or text == 'false':
        return False


def tobool(val):
    return 'true' if val else 'false'


def db(val):
    return 20 * np.log10(val) if val else -np.inf


def println(buf):
    try:
        print(buf, flush=True)
    except BrokenPipeError:
        pass


def timestamp():
    return datetime.utcnow().strftime('%y%m%d%H%M%S')


# logger

def log_handler(log_level, message):
    log_text = {
        1: "FATAL",
        2: "CRITICAL",
        3: "ERROR",
        4: "WARNING",
        5: "NOTICE",
        6: "INFO",
        7: "DEBUG",
        8: "TRACE",
        9: "SSI"}
    ts = datetime.utcnow().strftime('%H:%M:%S')
    println("[{}] {}: {}".format(ts, log_text[log_level], message))


## setters

DEVICE_CHANNEL = 0

def set_gain_mode(radio, agc):
    try:
        return radio.setGainMode(SOAPY_SDR_RX, DEVICE_CHANNEL, agc)
    except RuntimeError:
        pass


def set_sample_rate(radio, rate=None):
    try:
        if rate is None:
            rate = max([ d.maximum() for d in radio.getSampleRateRange(SOAPY_SDR_RX, 0) ])
        return radio.setSampleRate(SOAPY_SDR_RX, DEVICE_CHANNEL, rate)
    except RuntimeError:
        pass


def set_gain(radio, gain=None):
    try:
        if gain is None:
            gain = radio.getGainRange(SOAPY_SDR_RX, DEVICE_CHANNEL).maximum()
        return radio.setGain(SOAPY_SDR_RX, DEVICE_CHANNEL, gain)
    except RuntimeError:
        pass


def set_frequency(radio, frequency=None):
    try:
        if frequency is None:
            frequency = min([ d.minimum() for d in 
                        radio.getFrequencyRange(SOAPY_SDR_RX, DEVICE_CHANNEL) ])
        return radio.setFrequency(SOAPY_SDR_RX, DEVICE_CHANNEL, frequency)
    except RuntimeError:
        pass


def set_radio_setting(radio, name, data):
    try:
        return radio.writeSetting(name, data)
    except RuntimeError:
        pass


## getters

def get_sample_rate(radio):
    return int(radio.getSampleRate(SOAPY_SDR_RX, DEVICE_CHANNEL))


def get_frequency(radio):
    return int(radio.getFrequency(SOAPY_SDR_RX, DEVICE_CHANNEL))


def get_gain_mode(radio):
    return radio.getGainMode(SOAPY_SDR_RX, DEVICE_CHANNEL)


def get_gain(radio):
    return radio.getGain(SOAPY_SDR_RX, DEVICE_CHANNEL)


def get_radio_setting(radio, name):
    settings = [ d.key for d in radio.getSettingInfo() ]
    if name in settings:
        return radio.readSetting(name) 


# WAV functions

def wav_systemtime(): 
    ts = datetime.utcnow()
    dow = (ts.weekday() + 1) % 7 # monday=0 for weekday(), sunday=0 for auxi
    msec = ts.microsecond // 1000
    return (ts.year, ts.month, dow, ts.day, ts.hour, ts.minute, ts.second, msec)


def wav_header(sample_bytes, freq, rate, rf64, data_size=None, **kw):
    MAX_UINT32 = 0xffffffff
    MAX_UINT64 = 0xffffffffffffffff
    data_size = MAX_UINT64 if data_size is None else data_size

    # setup
    channels = 2
    block_align = channels * sample_bytes

    # fmt
    fmt_format = 3 if sample_bytes == 4 else 1
    byte_rate = rate * block_align
    bits_per_sample = 8 * sample_bytes
    fmt_data = pack('<HHIIHH', fmt_format, channels, 
               rate, byte_rate, block_align, bits_per_sample)

    # auxi
    start_time = pack('<HHHHHHHH', *wav_systemtime())
    auxi_data = pack('<16s16sIIIIIIIII', start_time, start_time,
                freq, rate, 0, rate, 0, 0, 0, 0, 0)

    # riff
    riff_data = b'WAVE'
    riff_data += pack('<4sI', b'fmt ', len(fmt_data)) + fmt_data
    riff_data += pack('<4sI', b'auxi', len(auxi_data)) + auxi_data

    if rf64:
        # ds64
        ds64_format = '<QQQ'
        sample_count = data_size // block_align
        riff_size = data_size + len(riff_data) + 16 + calcsize(ds64_format)
        ds64_data = pack(ds64_format, min(riff_size, MAX_UINT64), data_size, sample_count)

        # riff continued
        riff_data += pack('<4sI', b'ds64', len(ds64_data)) + ds64_data
        riff_data += pack('<4sI', b'data', MAX_UINT32)
        riff_size = MAX_UINT32
        buf = pack('<4sI', b'RF64', riff_size) + riff_data
    else:
        riff_data += pack('<4sI', b'data', min(data_size, MAX_UINT32))
        riff_size = data_size + len(riff_data)
        buf = pack('<4sI', b'RIFF', min(riff_size, MAX_UINT32)) + riff_data

    return buf


#########################
# web server
#########################

def server(payload):

    class HTTPRequestHandler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def send_chunk(self, buf):
            self.wfile.write(b'%X\r\n' % len(buf))
            self.wfile.write(buf)
            self.wfile.write(b'\r\n')

        def http_streaming(self, sample_bytes):
            q = Queue(maxsize=payload['maxsize'])
            with payload['qlock']:
                payload['queues'].append(q)
            try:
                self.send_response(200)
                self.send_header('Transfer-Encoding', 'chunked')
                self.send_header('Content-Type', 'audio/wav')
                self.end_headers()
                buf = wav_header(**dict(payload, **{ 
                                 'sample_bytes': sample_bytes, 
                                 'rf64': False }))
                self.send_chunk(buf)
                while True:
                    d = q.get()
                    if sample_bytes == 2:
                        d = np.ceil(0x8000 * d).astype(np.int16)
                    self.send_chunk(d.tobytes())
            except (BrokenPipeError, ConnectionResetError):
                with payload['qlock']:
                    payload['queues'].remove(q)

        def text_response(self, data='OK', code=200):
            if data is None:
               data = 'Bad Request'
               code = 400 
            data = (str(data).rstrip() + '\n').encode()
            self.send_response(code)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', len(data))
            self.end_headers()
            self.wfile.write(data)

        def do_HEAD(self):
            self.text_response()

        def do_PUT(self):
            path = self.path.split('/')[1:]
            length = int(self.headers.get('Content-Length', 0))
            text = self.rfile.read(length).decode()
            if self.path == '/quit':
                if abool(text) is not None:
                    self.text_response()
                    if abool(text):
                        payload['quit'].set()
                    return
            elif self.path == '/rate':
                if afloat(text) is not None and payload['pause'].is_set():
                    set_sample_rate(radio, afloat(text)) 
                    return self.text_response()
            elif self.path == '/frequency':
                if afloat(text) is not None:
                    set_frequency(radio, afloat(text))
                    return self.text_response()
            elif self.path == '/gain':
                if afloat(text) is not None:
                    set_gain_mode(radio, False)
                    set_gain(radio, afloat(text))
                    return self.text_response()
            elif self.path == '/agc':
                if abool(text) is not None:
                    set_gain_mode(radio, abool(text))
                    return self.text_response()
            elif self.path == '/pause':
                if abool(text) is not None:
                    if abool(text):
                        payload['pause'].set()
                    else:
                        payload['pause'].clear()
                    return self.text_response()
            elif path[0] == 'setting' and len(path) == 2: 
                set_radio_setting(radio, path[1], text.strip())
                return self.text_response()
            else:
                return self.text_response('Not Found', code=404)
            self.text_response(None)

        do_POST = do_PUT

        def do_GET(self):
            path = self.path.split('/')[1:]
            if self.path == '/quit':
               data = tobool(payload['quit'].is_set())
               self.text_response(data)
            elif self.path == '/rate':
               self.text_response(get_sample_rate(radio))
            elif self.path == '/frequency':
               self.text_response(get_frequency(radio))
            elif self.path == '/gain':
               self.text_response(get_gain(radio))
            elif self.path == '/agc':
               self.text_response(tobool(get_gain_mode(radio)))
            elif self.path == '/peak':
               data = '{:.2f}'.format(db(payload['peak']))
               self.text_response(data)
            elif self.path == '/pause':
               data = tobool(payload['pause'].is_set())
               self.text_response(data)
            elif path[0] == 'setting' and len(path) == 2:
               self.text_response(get_radio_setting(radio, path[1]))
            elif self.path == '/setting':
               data = ''
               for d in radio.getSettingInfo():
                   value = radio.readSetting(d.key)
                   data += '{}: {}\n'.format(d.key, value)
               self.text_response(data)
            elif self.path == '/s16':
               self.http_streaming(sample_bytes=2)
            elif self.path == '/f32':
               self.http_streaming(sample_bytes=4)
            else:
               self.text_response('Not Found', code=404)

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    radio = payload['radio']
    address = payload['address']
    println('Starting server on host "{}" port {}'.format(*address))
    httpd = ThreadingHTTPServer(address, HTTPRequestHandler)
    httpd.serve_forever()


#########################
# peak meter
#########################

def meter(payload, q):
    refresh = 2 * payload['refresh'] * payload['rate']
    level = 0
    count = 0
    while True:
        d = q.get()
        if refresh > 0:
            level = max(level, abs(d).max())
            count += d.size
            if count > refresh:
                payload['peak'] = level
                if not payload['quiet']:
                    println('{:.2f} dB'.format(db(level)))
                level = 0
                count = 0


#########################
# writer
#########################

def record(payload, q):
    sample_bytes = payload['sample_bytes']

    # get filename
    basename, ext = os.path.splitext(payload['output'])
    if not payload['notimestamp']:
        basename = '{}_{}'.format(basename, timestamp())
    filename = '{}{}'.format(basename, ext or '.wav')

    # open wav file
    println('Writing stream to WAV file: "{}".'.format(filename))
    wav_file = open(filename, "wb+")
    wav_buf = wav_header(**payload)
    wav_file.write(wav_buf)

    # begin recording
    try:
        data_size = 0
        while not payload['quit'].is_set() and not payload['pause'].is_set():
            d = q.get()
            if sample_bytes == 2:
                d = np.ceil(0x8000 * d).astype(np.int16)
            wav_file.write(d)
            data_size += d.nbytes

        wav_file.seek(0)
        wav_file.write(wav_header(data_size=data_size, **payload))
        wav_file.close()
        println('WAV file closed.')
    except OSError as e:
        payload['quit'].set()
        println('Fatal error: {}'.format(e))


def writer(payload, q):
    while not payload['quit'].is_set():
        while not payload['quit'].is_set() and payload['pause'].is_set():
            d = q.get()
        if not payload['quit'].is_set():
            record(payload, q)
    payload['done'].set()


#########################
# radio
#########################

def show_radio_setting(radio, name):
    data = get_radio_setting(radio, name)
    data = 'unknown' if data is None else data
    println('{:14s}: {:>11s}'.format(name, data))


def capture(radio):
    set_sample_rate(radio, args.rate)
    set_frequency(radio, args.frequency)
    if args.agc:
        set_gain(radio)
        set_gain_mode(radio, True)
    else:
        set_gain_mode(radio, False)
        set_gain(radio, args.gain)

    # settings
    if args.iq_swap: set_radio_setting(radio, 'iq_swap', 'true')
    if args.biastee: set_radio_setting(radio, 'biastee', 'true')
    if args.digital_agc: set_radio_setting(radio, 'digital_agc', 'true')
    if args.offset_tune: set_radio_setting(radio, 'offset_tune', 'true')
    if args.direct_samp: set_radio_setting(radio, 'direct_samp', args.direct_samp)

    # get info
    rate = get_sample_rate(radio)
    freq = get_frequency(radio)

    # show info
    println('Sampling Rate: {:11.6f} MHz'.format(rate / 1e6))
    println('Frequency:     {:11.6f} MHz'.format(freq / 1e6))
    println('AGC:           {:>11s}'.format(tobool(get_gain_mode(radio))))
    println('Gain:          {:11.4g} dB'.format(get_gain(radio)))

    # show settings
    show_radio_setting(radio, 'iq_swap')
    show_radio_setting(radio, 'biastee')
    show_radio_setting(radio, 'digital_agc')
    show_radio_setting(radio, 'offset_tune')
    show_radio_setting(radio, 'direct_samp')

    # data packet
    data = np.array([0] * 2 * args.packet_size, np.float32)

    # setup 
    maxsize = args.buffer_size * 2**20 // data.nbytes
    q_writer = Queue(maxsize=maxsize)
    q_meter = Queue(maxsize=maxsize)

    # payload
    payload = {
        'sample_bytes': 2 if args.pcm16 else 4,
        'quiet': args.quiet,
        'rf64': args.rf64,
        'refresh': args.refresh,
        'address': (args.hostname, args.port),
        'output': args.output,
        'notimestamp': args.notimestamp,
        ####
        'radio': radio,
        'freq': freq,
        'rate': rate,
        'peak': np.nan,
        ####
        'maxsize': maxsize,
        'queues': [],
        'qlock': Lock(),
        'pause': Event(),
        'quit': Event(),
        'done': Event()
    }

    # pause recording?
    if args.pause:
        payload['pause'].set()

    # start writer thread
    payload['queues'].append(q_writer)
    t_writer = Thread(target=writer, args=(payload, q_writer), daemon=True)
    t_writer.start()

    # start peak meter thread
    payload['queues'].append(q_meter)
    t = Thread(target=meter, args=(payload, q_meter), daemon=True)
    t.start()

    # start webserver thread
    t = Thread(target=server, args=(payload,), daemon=True)
    t.start()

    # start stream
    stream = radio.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
    radio.activateStream(stream) 
    while not payload['done'].is_set():
        try:
            radio.readStream(stream, [data], args.packet_size)
            d = data.copy()
            for q in payload['queues']:
                q.put(d)
        except (KeyboardInterrupt, SystemError):
            println('\nCapture interrupted, quitting.')
            payload['quit'].set()


#########################
# main
#########################

def main():
    SoapySDR.registerLogHandler(log_handler)

    # enumerate
    available = [ d['driver'] for d in SoapySDR.Device.enumerate() ]
    if not available:
        println('No radio devices available.')
        return 

    # list device
    if args.list:
        for i, name in enumerate(available):
            println('{}. {}'.format(i+1, name))
        return

    # open radio
    device = args.device or available[0]
    radio = SoapySDR.Device({ 'driver': device })

    # steam radio
    capture(radio)


if __name__ == '__main__':
    args = parse_args()
    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
    main()

