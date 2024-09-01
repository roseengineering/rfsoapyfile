#!/usr/bin/python3

import os, subprocess 

def run(command, language=''):
    proc = subprocess.Popen("PYTHONPATH=. python3 soapyfile/" + command, shell=True, stdout=subprocess.PIPE)
    buf = proc.stdout.read().decode()
    proc.wait()
    text = f"""
```{language}
$ {command}
{buf}\
```
"""
    return text.replace('soapyfile.py', 'soapyfile')

print(f"""

# rfsoapyfile

A Python 3 script for capturing and recording a SDR stream to a WAV file, or serving it as a HTTP audio stream.
The script is threaded for high performance, especially
on a Raspberry Pi.  The script includes a REST API
for controlling the capture and WAV recording remotely.

The script will save the WAV stream in either the RF64 or WAV(32) file format.
By default the recording is saved in the WAV(32) format using 32-bit IEEE floating point PCM samples.
To save using 16-bit PCM samples use the --pcm option.
The SDR specific 'auxi' 
metadata chunk, with record time and center frequency information, is added to the WAV audio file as well.

To quit the script and close the recording type control-C, or use the /quit REST call.


## Dependencies

The script requires the numpy and SoapySDR Python libraries.

## Example

```
$ soapyfile -f 100.1e6 -r 1e6 --pcm -g 42 --output out
```

## Installation

Either 

1) copy the file 'soapyfile/soapyfile.py' to where ever you want it
and then execute it directly using "python soapyfile.py" or 

2) install soapyfile using pip.  Specifically, cd into the directory where you cloned this repository, and then run "pip install .", note the dot.
Or you can use "pip install git+https://github.com/roseengineering/rfsoapyfile".  Now you can run "soapyfile" as a normal command in the shell.


## Usage

{ run("soapyfile.py --help") }

## REST API

The REST API is available off port 8080.  Use POST or PUT to change
a program or radio setting.  Use GET to view it.  If a boolean is needed, the following
strings are accepted: y, n, yes, no, true, and false.  
Pausing the recording closes the WAV output file, while unpausing the recording creates
a new output file.   The SDR stream is always being captured even when the recording is paused.
Note, if the option --notimestamp is enabled, any previously existing
output file of the same name will be overwritten should you pause and unpause.


```
PUT /quit              <bool>      stop capture and terminate program, yes or no
PUT /rate              <float>     set sampling rate (Hz), if recording paused
PUT /frequency         <float>     set center frequency (Hz)
PUT /gain              <float>     set gain (dB)
PUT /agc               <bool>      enable agc, yes or no
PUT /pause             <bool>      pause the file recording, yes or no
PUT /setting/<name>    <string>    change named soapy SDR setting

GET /rate              return sampling rate (Hz)
GET /frequency         return center frequency (Hz)
GET /gain              return gain (Hz)
GET /agc               return AGC setting (bool)
GET /pause             return whether the file recording is paused (bool)
GET /setting           return a list of the available SDR soapy settings and their values
GET /setting/<name>    return the value of the named soapy SDR setting

GET /bins              return the size of the running FFT
GET /rbw               return the RBW of the running FFT
GET /average           return the number of FFTs being averaged
GET /integration       return the integration time of the averaged FFTs
```

The IQ data is streamed out of URL paths /pcm, /float, and /cf32.
The /pcm endpoint streams 16 bit integer WAV.  The /float endpoint streams 32-bit
float WAV.  While the /cf32 endpoint streams in raw cf32 format.  Run soapyfile with the --pause option if
you only want to stream over HTTP.  (No SDR program that I know of currently supports HTTP streams,
however it might be useful for remote operation or sharing a stream in real time.)

Peak sample data (dBFS) and frequency power data (rtl_power output format) is streamed out of URL paths /peak and /power as text.

```
GET /pcm               return a 16-bit integer PCM WAV HTTP audio stream
GET /float             return a 32-bit IEEE floating point WAV HTTP audio stream
GET /cf32              return a 32-bit IEEE floating point raw "cf32" HTTP audio stream
GET /peak              return latest ADC peak values (dBFS) as a HTTP stream
GET /power             return power values (dB) of the FTT as a HTTP stream in rtl_power output format
GET /waterfall         return an ascii waterfall of the FTT as a HTTP stream
```

Here are some sample curl commands:

```
curl localhost:8080/float --output out.wav
curl -d yes localhost:8080/agc
curl -d y localhost:8080/quit
curl -d n localhost:8080/pause
curl -d true localhost:8080/pause
curl -d 40.1 localhost:8080/gain
curl -d 100e6 localhost:8080/frequency
curl localhost:8080/pause
curl localhost:8080/agc
curl localhost:8080/gain
curl localhost:8080/peak
curl localhost:8080/frequency
```

For example, running the following curl commands I get:

```
$ curl -d 103e6 localhost:8080/frequency
OK
$ curl localhost:8080/frequency
103000000
```

```
$ curl -s localhost:8080/setting
sample_offset: "0"
rig: "0"
rig_rate: "0"
rig_port: ""
```

```
$ curl -i localhost:8080/float 
HTTP/1.1 200 OK
Server: BaseHTTP/0.6 Python/3.12.5
Date: Sun, 01 Sep 2024 15:08:34 GMT
Transfer-Encoding: chunked
Content-Disposition: inline; filename="10000000_48000_240901150834.wav"
Content-Type: audio/wav

Warning: Binary output can mess up your terminal. Use "--output -" to tell 
Warning: curl to output it to your terminal anyway, or consider "--output 
Warning: <FILE>" to save to a file.
```

```
$ curl -i localhost:8080/cf32
HTTP/1.1 200 OK
Server: BaseHTTP/0.6 Python/3.12.5
Date: Sun, 01 Sep 2024 15:08:38 GMT
Transfer-Encoding: chunked
Content-Disposition: inline; filename="10000000_48000_240901150838.cf32"
Content-Type: audio/cf32

Warning: Binary output can mess up your terminal. Use "--output -" to tell 
Warning: curl to output it to your terminal anyway, or consider "--output 
Warning: <FILE>" to save to a file.
```

```
$ curl -s localhost:8080/peak
-120.0
-120.0
-120.0
-120.0
-120.0
^C
```

```
$ curl -s localhost:8080/power
2024-09-01,15:37:21,9976000,10023250,750,48000,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0
2024-09-01,15:37:22,9976000,10023250,750,48000,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0
2024-09-01,15:37:23,9976000,10023250,750,48000,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0
^C
```

```
$ curl -s localhost:8080/waterfall
................................................................ -120.0
................................................................ -120.0
................................................................ -120.0
................................................................ -120.0
................................................................ -120.0
^C
```

## Benchmarks

My Raspberry Pi 3A+ is able to support up to a 1.5M sample rate with the RTLSDR before it overflows.  Here is the core usage:

![htop command](res/pi3aplus.png)

While my Raspberry Pi 4B is able to support up to a 2.0M sample rate with the RTLSDR.

![htop command](res/pi4b.png)

The Raspberry Pi Zero W Version 1 only has one core, so threading does not help. The best
it could support was a 300K sampling rate.

![htop command](res/pizero1.png)

Version 2 of the Zero has four cores, however I do not have one to test against.

## Notes

The script uses the threading library to provide multithreading.  Despite the GIL lock
using this library was much faster than using the multiprocessing library performance-wise.
The need to copy streaming data across process spaces was probably too much of a hit.

""")


