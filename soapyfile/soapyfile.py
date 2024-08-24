#!/usr/bin/python3

import os
import sys
import time
import datetime
import argparse
import numpy as np
from struct import pack, calcsize
from queue import Queue
from threading import Thread, Lock
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

DEVICE_CHANNEL = 0


def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-l', '--list', action='store_true', help='list available device names')
    parser.add_argument('-d', '--device', help='device string, eg driver=rtlsdr')
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
    if text == 'y' or text == 'yes' or text == 'true' or text == '1':
        return True
    if text == 'n' or text == 'no' or text == 'false' or text == '0':
        return False


def tobool(val):
    return 'true' if val else 'false'


def println(buf):
    try:
        print(buf, flush=True)
    except BrokenPipeError:
        pass


def timestamp():
    return datetime.datetime.now(datetime.UTC).strftime('%y%m%d%H%M%S')


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
    ts = datetime.datetime.now(datetime.UTC).strftime('%H:%M:%S')
    println("[{}] {}: {}".format(ts, log_text[log_level], message))


## soapysdr setters

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


## soapysdr getters

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
    ts = datetime.datetime.now(datetime.UTC)
    dow = (ts.weekday() + 1) % 7 # monday=0 for weekday(), sunday=0 for auxi
    msec = ts.microsecond // 1000
    return (ts.year, ts.month, dow, ts.day, ts.hour, ts.minute, ts.second, msec)


def wav_header(sample_bytes, frequency, rate, rf64=False, data_size=None, **kw):
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
                frequency, rate, 0, rate, 0, 0, 0, 0, 0)

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
# singletons
#########################



class PeakMeter:
    def __init__(self):
        self.resolution = np.finfo(np.float32).resolution
        self.peak_db = -np.inf

    def initialize(self, state):
        self.state = state

    def refresh_count(self):
        return 2 * self.state.refresh * self.state.rate  # two channels

    def set_peak(self, peak):
        self.peak_db = 20 * np.log10(peak + self.resolution)
        if not self.state.quiet:
            println('{:.2f} dBFS'.format(self.peak_db))
    

class QueueInventory:
    def __init__(self):
        self.lock = Lock()
        self.inventory = []

    def initialize(self, maxsize):
        self.maxsize = maxsize 

    def checkout_item(self):
        q = Queue(maxsize=self.maxsize)
        with self.lock:
            self.inventory.append(q)
        return q
    
    def return_item(self, q):
        with self.lock:
            self.inventory.remove(q)

    def current(self):
        with self.lock:
            return list(self.inventory)
 

class State:
    def initialize(
            self, refresh, quiet, pause, rate, 
            frequency, radio, notimestamp, output,
            hostname, port, rf64, sample_bytes, **kw):
        self.refresh = refresh
        self.quiet = quiet
        self.pause = pause
        self.rate = rate
        self.frequency = frequency
        self.radio = radio
        self.notimestamp = notimestamp
        self.output = output
        self.hostname = hostname
        self.sample_bytes = sample_bytes
        self.port = port
        self.rf64 = rf64
        self.done = False
        self.quit = False

        
queue_inventory = QueueInventory()
peak_meter = PeakMeter()
state = State()


#########################
# web server
#########################

def server():

    class HTTPRequestHandler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def send_chunk(self, buf):
            self.wfile.write(b'%X\r\n' % len(buf))
            self.wfile.write(buf)
            self.wfile.write(b'\r\n')

        def http_streaming(self, sample_bytes):
            q = queue_inventory.checkout_item()
            try:
                self.send_response(200)
                self.send_header('Transfer-Encoding', 'chunked')
                self.send_header('Content-Type', 'audio/wav')
                self.end_headers()
                buf = wav_header(
                    sample_bytes=sample_bytes, 
                    frequency=state.frequency, 
                    rate=state.rate)
                self.send_chunk(buf)
                while True:
                    d = q.get()
                    if sample_bytes == 2:
                        d = np.ceil(0x8000 * d).astype(np.int16)
                    self.send_chunk(d.tobytes())
            except (BrokenPipeError, ConnectionResetError):
                queue_inventory.return_item(q)

        def text_response(self, data=None, code=200, success=True):
            if not success:
               data = 'Bad Request'
               code = 400 
            elif data is None:
               data = 'OK'
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
            success = False
            if self.path == '/quit':
                if abool(text) is not None:
                    self.text_response()
                    state.quit = abool(text)
                    return
            elif self.path == '/rate':
                # recording must be paused to change the sampling rate
                if afloat(text) is not None and state.pause:
                    set_sample_rate(state.radio, afloat(text)) 
                    success = True
            elif self.path == '/frequency':
                if afloat(text) is not None:
                    set_frequency(state.radio, afloat(text))
                    success = True
            elif self.path == '/gain':
                if afloat(text) is not None:
                    set_gain_mode(state.radio, False)
                    set_gain(radio, afloat(text))
                    success = True
            elif self.path == '/agc':
                if abool(text) is not None:
                    set_gain_mode(state.radio, abool(text))
                    success = True
            elif self.path == '/pause':
                if abool(text) is not None:
                    state.pause = abool(text)
                    success = True
            elif path[0] == 'setting' and len(path) == 2: 
                set_radio_setting(state.radio, path[1], text.strip())
                success = True
            else:
                return self.text_response('Not Found', code=404)
            self.text_response(success=success)

        do_POST = do_PUT

        def do_GET(self):
            data = None
            path = self.path.split('/')[1:]
            if self.path == '/quit':
               data = tobool(state.quit)
            elif self.path == '/rate':
               data = get_sample_rate(state.radio)
            elif self.path == '/frequency':
               data = get_frequency(state.radio)
            elif self.path == '/gain':
               data = get_gain(state.radio)
            elif self.path == '/agc':
               data = tobool(get_gain_mode(state.radio))
            elif self.path == '/peak':
               data = '{:.2f}'.format(peak_meter.peak_db)
            elif self.path == '/pause':
               data = tobool(state.pause)
            elif path[0] == 'setting' and len(path) == 2:
               data = get_radio_setting(state.radio, path[1])
            elif self.path == '/setting':
               data = ''
               for d in state.radio.getSettingInfo():
                   value = state.radio.readSetting(d.key)
                   data += '{}: {}\n'.format(d.key, value)
            elif self.path == '/s16':
               return self.http_streaming(sample_bytes=2)
            elif self.path == '/cf32':
               return self.http_streaming(sample_bytes=4)
            else:
               return self.text_response('Not Found', code=404)
            self.text_response(data)

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    address = (state.hostname, state.port)
    println('Starting server on host "{}" port {}'.format(*address))
    httpd = ThreadingHTTPServer(address, HTTPRequestHandler)
    httpd.serve_forever()


#########################
# peak meter
#########################




###

def meter():
    q = queue_inventory.checkout_item()
    resolution = np.finfo(np.float32).resolution
    peak = 0
    count = 0
    while peak_meter.refresh_count() > 0:
        d = q.get()
        peak = max(peak, abs(d).max())
        count += d.size
        if count > peak_meter.refresh_count():
            peak_meter.set_peak(peak)
            peak = 0
            count = 0
    queue_inventory.return_item(q)


#########################
# writer
#########################

def record(q):
    # get filename
    basename, ext = os.path.splitext(state.output)
    if not state.notimestamp:
        basename = '{}_{}'.format(basename, timestamp())
    filename = '{}{}'.format(basename, ext or '.wav')

    # open wav file
    println('Writing stream to WAV file: "{}".'.format(filename))
    wav_file = open(filename, "wb+")
    param = {
        'sample_bytes': state.sample_bytes, 
        'frequency': state.frequency, 
        'rate': state.rate, 
         'rf64': state.rf64
    }
    wav_buf = wav_header(**param)
    wav_file.write(wav_buf)

    # begin recording
    try:
        data_size = 0
        while not state.quit and not state.pause:
            d = q.get()
            if state.sample_bytes == 2:
                d = np.ceil(0x8000 * d).astype(np.int16)
            wav_file.write(d)
            data_size += d.nbytes
        wav_file.seek(0)
        wav_file.write(wav_header(data_size=data_size, **param))
        wav_file.close()
        println('WAV file closed.')
    except OSError as e:
        state.quit = True
        println('Fatal error: {}'.format(e))


def writer():
    q = queue_inventory.checkout_item()
    while not state.quit:
        while not state.quit and state.pause:
            d = q.get()
        if not state.quit:
            record(q)
    state.done = True
    queue_inventory.return_item(q)


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
    args.rate = get_sample_rate(radio)
    args.frequency = get_frequency(radio)
    sample_bytes = 2 if args.pcm16 else 4

    # show info
    println('Sampling Rate: {:11.6f} MHz'.format(args.rate / 1e6))
    println('Frequency:     {:11.6f} MHz'.format(args.frequency / 1e6))
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
    queue_inventory.initialize(maxsize)

    # setup state
    kw = args.__dict__
    state.initialize(radio=radio, sample_bytes=sample_bytes, **kw)
    
    # setup peak meter
    peak_meter.initialize(state)

    # start writer thread
    t_writer = Thread(target=writer, daemon=True)
    t_writer.start()

    # start peak meter thread
    t = Thread(target=meter, daemon=True)
    t.start()

    # start webserver thread
    t = Thread(target=server, daemon=True)
    t.start()

    # start stream
    stream = radio.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
    radio.activateStream(stream) 
    while not state.done:
        try:
            radio.readStream(stream, [data], args.packet_size)
            d = data.copy()
            for q in queue_inventory.current():
                q.put(d)
        except (KeyboardInterrupt, SystemError):
            println('\nCapture interrupted, quitting.')
            state.quit = True


#########################
# main
#########################

def main():
    global args, SOAPY_SDR_RX, SOAPY_SDR_CF32

    args = parse_args()

    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32

    SoapySDR.registerLogHandler(log_handler)

    # enumerate
    available = SoapySDR.Device.enumerate()
    if not available:
        println('No radio devices available.')
        return 

    # list device
    if args.list:
        indent = 35
        print(f'{"Device String":{indent}s} Label')
        for d in available:
            driver = d['driver']
            label = d['label']
            device_string = f'driver={driver}'
            for name in [ 'device_id', 'serial', 'hardware' ]:
                if name in d:
                    device_string += f',{name}={d[name]}'
            println(f'{device_string:{indent}s} {label}')
        return

    # open radio
    device = args.device or available[0]
    radio = SoapySDR.Device(device)

    # steam radio
    capture(radio)


if __name__ == '__main__':
    main()

