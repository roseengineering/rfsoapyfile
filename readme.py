#!/usr/bin/python3

import os, subprocess 

def run(command, language=''):
    proc = subprocess.Popen("PYTHONPATH=. python3 " + command, shell=True, stdout=subprocess.PIPE)
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

A Python 3 script for capturing and recording a SDR stream to a WAV file (or serving it as a HTTP audio stream).
The script is threaded for high performance, especially
on a Raspberry Pi.  The script includes a REST API
for controlling the capture and WAV recording remotely.

The script will save the stream in either RF64 or WAV file format.
By default the recording is saved in the WAV format using 32-bit floating point PCM IQ samples.
To save using 16-bit PCM samples use the --pcm16 option.
The SDR specific 'auxi' 
metadata chunk, with record time and center frequency information, is added to the audio file as well.

## Dependencies

The script requires the numpy and SoapySDR Python libraries.

## Example

```
$ python soapyfile.py -f 100.1e6 -r 1e6 --pcm16 -g 42 --output out --pause
```

## Usage

{ run("soapyfile.py --help") }

## REST API

The REST API is available off port 8080.  Use POST or PUT to change
a program or radio setting.  Use GET to view it.  If a boolean is needed, the following
strings are accepted: y, n, yes, no, true, and false.  Unpausing the stream creates
a new WAV file.   If the option --notimestamp is enabled, this means any existing
output file will be overwritten.

```
PUT /quit              <bool>      stop recording and terminate program, yes or no
PUT /rate              <float>     set sampling rate (Hz) but only if recording is paused
PUT /frequency         <float>     set center frequency (Hz)
PUT /gain              <float>     set gain (dB)
PUT /agc               <bool>      enable agc, yes or no
PUT /pause             <bool>      pause recording, yes or no
PUT /setting/<name>    <string>    change named soapy setting

GET /rate              return sampling rate (Hz)
GET /frequency         return center frequency (Hz)
GET /gain              return gain (Hz)
GET /agc               return AGC setting (yes or no)
GET /pause             return whether the recording is paused (yes or no)
GET /setting           return list of available soapy setting names
GET /setting/<name>    return value of named soapy setting

GET /s16               return a 16-bit integer PCM WAV HTTP audio stream
GET /f32               return a 32-bit floating point PCM WAV HTTP audio stream
```

Here are some examples using curl:

```bash
curl -i localhost:8080/f32 --output out.wav
curl -d yes localhost:8080/agc
curl -d yes localhost:8080/quit
curl -d yes localhost:8080/pause
curl -d 40.1 localhost:8080/gain
curl -d 100e6 localhost:8080/frequency
curl localhost:8080/pause
curl localhost:8080/agc
curl localhost:8080/gain
curl localhost:8080/frequency
```

""")


