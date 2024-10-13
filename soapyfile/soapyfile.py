#!/usr/bin/env python3

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


def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-l', '--list', action='store_true', help='list available device names')
    parser.add_argument('-d', '--device', help='device string, eg. driver=rtlsdr')

    # device options
    group = parser.add_argument_group('device options')
    group.add_argument('-f', '--frequency', type=float, help='center frequency (Hz)')
    group.add_argument('-r', '--rate', type=float, help='sampling rate (Hz)')
    group.add_argument('-g', '--gain', type=float, help='front end gain (dB)')
    group.add_argument('-a', '--agc', action='store_true', help='enable AGC')
    group.add_argument('--iq-swap', action='store_true', help='swap IQ signals')
    group.add_argument('--biastee', action='store_true', help='enable bias tee')
    group.add_argument('--digital-agc', action='store_true', help='enable digital AGC')
    group.add_argument('--offset-tune', action='store_true', help='enable offset tune')
    group.add_argument('--direct-samp', type=int, help='select I or Q channel: 1 or 2')

    # output file options
    group = parser.add_argument_group('output file options')
    group.add_argument('--output', default='output', help='output file name')
    group.add_argument('--pause', action='store_true', help='no file output until unpaused')
    group.add_argument('--pcm', action='store_true', help='write 16-bit PCM samples for WAV')
    group.add_argument('--cf32', action='store_true', help='write as .c32 raw file rather than WAV')
    group.add_argument('--rf64', action='store_true', help='write RF64 file for WAV')
    group.add_argument('--notimestamp', action='store_true', help='no timestamp appended file name')

    # streaming options
    group = parser.add_argument_group('streaming options')
    group.add_argument('--packet-size', default=1024, type=int, help='soapysdr packet size in bytes')
    group.add_argument('--buffer-size', default=256, type=int, help='stream buffer size in MB')

    # power measurment options
    group = parser.add_argument_group('power measurement options')
    group.add_argument('--bins', default=64, type=int, help='size of the fft to use ')
    group.add_argument('--rbw', type=float, help='resolution bandwidth (Hz), overrides bins')
    group.add_argument('--integration', default=1, type=float, help='integration time for rbw option')
    group.add_argument('--average', type=int, help='number of ffts to average, overrides integration')

    # rest server options
    group = parser.add_argument_group('REST server options')
    group.add_argument('--hostname', default='0.0.0.0', help='REST server hostname')
    group.add_argument('--port', default=8080, type=int, help='REST server port number')

    # console options
    group = parser.add_argument_group('console options')
    group.add_argument('--waterfall', action='store_true', help='show a streaming ascii waterfall')
    group.add_argument('--meter', action='store_true', help='show streaming peak values in dBFS')
    group.add_argument('--refresh', default=1, type=float, help='peak meter refresh (sec)')
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
    now = datetime.datetime.now(datetime.UTC)
    return now.strftime('%y%m%d%H%M%S')


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
    now = datetime.datetime.now(datetime.UTC)
    ts = now.strftime('%H:%M:%S')
    println("[{}] {}: {}".format(ts, log_text[log_level], message))


## soapysdr setters

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


class QueueInventory:
    def __init__(self):
        self.lock = Lock()
        self.inventory = []
        self.maxsize = 0

    def initialize(self, maxsize):
        self.maxsize = maxsize 

    def checkout_item(self):
        # if maxsize is 0 or less then queue size is infinite
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
            self, refresh, pause, rate, frequency, radio, 
            notimestamp, output, hostname, port, rf64, pcm,
            cf32, rbw, bins, integration, average, waterfall,
            meter, **kw):
        self.refresh = refresh
        self.pause = pause
        self.rate = rate
        self.frequency = frequency
        self.radio = radio
        self.notimestamp = notimestamp
        self.output = output
        self.hostname = hostname
        self.sample_bytes = 2 if pcm else 4
        self.port = port
        self.rf64 = rf64
        self.cf32 = cf32
        state.rbw = rbw
        state.bins = bins
        state.integration = integration
        state.average = average
        state.waterfall = waterfall
        state.meter = meter
        self.done = False
        self.quit = False

        
peak_queue_inventory = QueueInventory()
power_queue_inventory = QueueInventory()
stream_queue_inventory = QueueInventory()
waterfall_queue_inventory = QueueInventory()
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

        def text_streaming(self, queue_inventory):
            q = queue_inventory.checkout_item()
            try:
                self.send_response(200)
                self.send_header('Transfer-Encoding', 'chunked')
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                while True:
                    text = f'{q.get()}\n'
                    self.send_chunk(text.encode())
            except (BrokenPipeError, ConnectionResetError):
                queue_inventory.return_item(q)

        def audio_streaming(self, sample_bytes=None):
            q = stream_queue_inventory.checkout_item()
            filename = f'{state.frequency:.0f}_{state.rate:.0f}_{timestamp()}'
            filename += '.wav' if sample_bytes else '.cf32'
            content_type = 'audio/wav' if sample_bytes else 'audio/cf32'
            try:
                self.send_response(200)
                self.send_header('Transfer-Encoding', 'chunked')
                self.send_header('Content-Disposition', f'inline; filename="{filename}"')
                self.send_header('Content-Type', content_type)
                self.end_headers()
                if sample_bytes:
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
                stream_queue_inventory.return_item(q)

        def text_response(self, data=None, code=200, success=True):
            if not success:
                text = 'Bad Request'
                code = 400 
            elif data is None:
                text = 'OK'
            else:
                text = str(data).rstrip()
            text += '\n'
            buf = text.encode()
            self.send_response(code)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', len(buf))
            self.end_headers()
            self.wfile.write(buf)

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
                if afloat(text) is not None and state.pause:
                    # recording must be paused to change the sampling rate
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
            if self.path == '/rate':
               data = get_sample_rate(state.radio)
            elif self.path == '/frequency':
               data = get_frequency(state.radio)
            elif self.path == '/gain':
               data = get_gain(state.radio)
            elif self.path == '/agc':
               data = tobool(get_gain_mode(state.radio))
            elif self.path == '/pause':
               data = tobool(state.pause)
            elif path[0] == 'setting' and len(path) == 2:
               data = get_radio_setting(state.radio, path[1])
            ###
            elif self.path == '/setting':
               data = ''
               for d in state.radio.getSettingInfo():
                   value = state.radio.readSetting(d.key)
                   data += '{}: "{}"\n'.format(d.key, value)
            elif self.path == '/bins':
               data = state.bins
            elif self.path == '/rbw':
               data = state.rbw
            elif self.path == '/integration':
               data = state.integration
            elif self.path == '/average':
               data = state.average
            ###
            elif self.path == '/waterfall':
               return self.text_streaming(waterfall_queue_inventory)
            elif self.path == '/power':
               return self.text_streaming(power_queue_inventory)
            elif self.path == '/peak':
               return self.text_streaming(peak_queue_inventory)
            elif self.path == '/pcm':
               return self.audio_streaming(sample_bytes=2)
            elif self.path == '/float':
               return self.audio_streaming(sample_bytes=4)
            elif self.path == '/cf32':
               return self.audio_streaming()
            else:
               return self.text_response('Not Found', code=404)
            self.text_response(data)

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    address = (state.hostname, state.port)
    println('Starting server on host "{}" port {}'.format(*address))
    try:
        httpd = ThreadingHTTPServer(address, HTTPRequestHandler)
        httpd.serve_forever()
    except OSError as e:
        println(f'\nREST server error "{e}", quitting.')
        state.done = True


#########################
# power meter
#########################

def meter_power():
    stream = stream_queue_inventory.checkout_item()
    resolution = np.finfo(np.float16).resolution
    scale = ".:-=+*#%@"

    fft_n = state.rate / state.rbw if state.rbw else state.bins
    fft_n = int(2**np.ceil(np.log(fft_n) / np.log(2)))
    fft_time = fft_n / state.rate # in seconds
    fft_freq = (state.frequency + 
                np.fft.fftshift(np.fft.fftfreq(fft_n, d=1/state.rate)))
    fft_start = fft_freq[0]
    fft_stop = fft_freq[-1]
    fft_step = fft_freq[1] - fft_freq[0]
    window = np.hanning(fft_n)
    data = np.zeros(2 * fft_n, dtype=np.float32)

    average = (state.average if state.average else 
               int(np.ceil(state.integration / fft_time)))
    total_samples = average * fft_n
    power = np.zeros((average, fft_n), dtype=np.float32)

    state.bins = fft_n
    state.rbw = state.rate / fft_n
    state.average = average
    state.integration = average * fft_time

    print(f'fft size = {state.bins}')
    print(f'average = {state.average}')
    print(f'rbw = {state.rbw:.2f} Hz')

    row = 0
    col = 0
    while True:
        d = stream.get()
        i = 0
        n = len(d)
        while i < n:
            size = min(n - i, 2 * fft_n - col)
            data[col:col+size] = d[i:i+size]
            i += size
            col += size
            if col < 2 * fft_n:
                break
            ps = data[::2] + data[1::2] * 1j
            ps = abs(np.fft.fft(ps * window)) / fft_n
            power[row,:] = np.fft.fftshift(ps)
            col = 0
            row += 1
            if row == average:
               row = 0 
               ps = np.average(power, axis=0)
               ps = 20 * np.log10((ps + resolution) / resolution)

               current = waterfall_queue_inventory.current()
               if state.waterfall or current:
                   ps -= min(ps)
                   values = len(scale) * ps / (max(ps) + 1e-3)
                   waterfall = ''.join([ scale[i] for i in values.astype(np.int32) ])
                   text = f'{waterfall} {state.dbfs:.2f}'
                   if state.waterfall:
                       print(text)
                   for q in current:
                       q.put(text)

               current = power_queue_inventory.current()
               if current:
                   now = datetime.datetime.now(datetime.UTC)
                   ds = now.strftime('%Y-%m-%d')
                   ts = now.strftime('%H:%M:%S')
                   dbm = ','.join(f'{d:.1f}' for d in ps)
                   text = f'{ds},{ts},{fft_start:.0f},{fft_stop:.0f},{fft_step:.0f},{total_samples},{dbm}'
                   for q in current:
                       q.put(text)


#########################
# peak meter
#########################

def meter_set_peak(x):
    state.dbfs = np.round(20 * np.log10(x + state.resolution), 1)

    
def meter_peak():
    state.resolution = np.finfo(np.float32).resolution
    meter_set_peak(0)
    stream = stream_queue_inventory.checkout_item()
    peak = 0
    count = 0
    while True:
        d = stream.get()
        peak = max(peak, abs(d).max())
        count += d.size
        if count > 2 * state.refresh * state.rate:
            meter_set_peak(peak)
            if state.meter and not state.waterfall:
                println(state.dbfs)
            for q in peak_queue_inventory.current():
                q.put(state.dbfs)
            peak = 0
            count = 0


#########################
# writer
#########################

def writer_record(q):
    # get filename
    basename, ext = os.path.splitext(state.output)
    if not state.notimestamp:
        basename = f'{basename}_{timestamp()}'
    default_ext = '.cf32' if state.cf32 else '.wav'
    filename = '{}{}'.format(basename, ext or default_ext)

    # open wav file
    println('Writing IQ stream to file: "{}".'.format(filename))
    fd = open(filename, "wb+")

    if not state.cf32:
        param = {
            'sample_bytes': state.sample_bytes, 
            'frequency': state.frequency, 
            'rate': state.rate, 
            'rf64': state.rf64
        }
        wav_buf = wav_header(**param)
        fd.write(wav_buf)

    # begin recording
    try:
        data_size = 0
        while not state.quit and not state.pause:
            d = q.get()
            if state.sample_bytes == 2:
                d = np.ceil(0x8000 * d).astype(np.int16)
            fd.write(d)
            data_size += d.nbytes
        if not state.cf32:
            fd.seek(0)
            fd.write(wav_header(data_size=data_size, **param))
        fd.close()
        println('IQ file closed.')
    except OSError as e:
        state.quit = True
        println('Fatal error: {}'.format(e))


def writer():
    q = stream_queue_inventory.checkout_item()
    while not state.quit:
        while not state.quit and state.pause:
            d = q.get()
        if not state.quit:
            writer_record(q)
    state.done = True


#########################
# radio
#########################

def show_radio_setting(radio, name):
    data = get_radio_setting(radio, name)
    data = 'unknown' if data is None else data
    println('{:14s}: {:>11s}'.format(name, data))


def capture(radio):
    state.initialize(radio=radio, **args.__dict__)

    # configure radio
    set_sample_rate(radio, args.rate)
    set_frequency(radio, args.frequency)
    if args.agc:
        set_gain(radio)
        set_gain_mode(radio, True)
    else:
        set_gain_mode(radio, False)
        set_gain(radio, args.gain)

    # extra 
    if args.iq_swap: set_radio_setting(radio, 'iq_swap', 'true')
    if args.biastee: set_radio_setting(radio, 'biastee', 'true')
    if args.digital_agc: set_radio_setting(radio, 'digital_agc', 'true')
    if args.offset_tune: set_radio_setting(radio, 'offset_tune', 'true')
    if args.direct_samp: set_radio_setting(radio, 'direct_samp', args.direct_samp)

    # get info
    state.rate = get_sample_rate(radio)
    state.frequency = get_frequency(radio)

    # show info
    println('Sampling Rate: {:11.6f} MHz'.format(state.rate / 1e6))
    println('Frequency:     {:11.6f} MHz'.format(state.frequency / 1e6))
    println('AGC:           {:>11s}'.format(tobool(get_gain_mode(radio))))
    println('Gain:          {:11.4g} dB'.format(get_gain(radio)))

    # show settings
    show_radio_setting(radio, 'iq_swap')
    show_radio_setting(radio, 'biastee')
    show_radio_setting(radio, 'digital_agc')
    show_radio_setting(radio, 'offset_tune')
    show_radio_setting(radio, 'direct_samp')

    # setup
    data = np.array([0] * 2 * args.packet_size, np.float32)
    maxsize = int(np.ceil(args.buffer_size * 2**20 / data.nbytes))
    stream_queue_inventory.initialize(maxsize)
    
    # start writer thread
    t = Thread(target=writer, daemon=True)
    t.start()

    # start power thread
    t = Thread(target=meter_power, daemon=True)
    t.start()

    # start peak meter thread
    t = Thread(target=meter_peak, daemon=True)
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
            for q in stream_queue_inventory.current():
                q.put(d)
        except SystemError as e:
            println(f'\nSystem error "{e}", quitting.')
            break
        except KeyboardInterrupt:
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

