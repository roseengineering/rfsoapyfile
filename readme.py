#!/usr/bin/python3

import os, subprocess 

def run(command, language=''):
    command = "PYTHONPATH=. python3 " + command
    proc = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
    buf = proc.stdout.read().decode()
    proc.wait()
    return f"""
```{language}
$ {command}
{buf}\
```
"""

print(f"""

# rfsoapyfile

A Python 3 script for capturing and recording a SDR stream to a WAV file (or HTTP audio stream).
The script is threaded for high performance, especially
on a Raspberry Pi.  The script includes a REST API
for controlling the capture and WAV recording remotely.

## Dependencies

The script requires the numpy and SoapySDR Python libraries.

## Usage

{ run("soapyfile.py --help") }

## REST API

The REST API is available off port 8080.  Use POST or PUT or change
a value.  Use GET to view it.  If a boolean is needed, the following
strings are accepted: y, n, yes, no, true, and false:

```
PUT /quit              <bool>      stop recording and terminate program, yes or no
PUT /rate              <float>     set sampling rate (Hz) but only if recording is stopped
PUT /frequency         <float>     set center frequency (Hz)
PUT /gain              <float>     set gain (dB)
PUT /agc               <bool>      enable agc, yes or no
PUT /pause             <bool>      stop recording, yes or no
PUT /setting/<name>    <string>    change named soapy setting

GET /rate              return sampling rate (Hz)
GET /frequency         return center frequency (Hz)
GET /gain              return gain (Hz)
GET /agc               return AGC setting (yes or no)
GET /pause             return pause status (yes or no)
GET /setting           return list of available soapy setting names
GET /setting/<name>    return value of named soapy setting

GET /s16               return 16-bit integer PCM WAV HTTP audio stream
GET /f32               return 32-bit floating point PCM WAV HTTP audio stream
```

""")


