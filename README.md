

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


```
$ soapyfile.py --help
usage: soapyfile.py [-h] [-l] [-d DEVICE] [-f FREQUENCY] [-r RATE] [-g GAIN]
                    [-a] [--iq-swap] [--biastee] [--digital-agc]
                    [--offset-tune] [--direct-samp DIRECT_SAMP] [--pcm16]
                    [--rf64] [--notimestamp] [--pause] [--output OUTPUT]
                    [--packet-size PACKET_SIZE] [--buffer-size BUFFER_SIZE]
                    [--hostname HOSTNAME] [--port PORT] [--refresh REFRESH]
                    [--quiet]

optional arguments:
  -h, --help            show this help message and exit
  -l, --list            list available device names (default: False)
  -d DEVICE, --device DEVICE
                        device name (default: None)
  -f FREQUENCY, --frequency FREQUENCY
                        center frequency (Hz) (default: None)
  -r RATE, --rate RATE  sampling rate (Hz) (default: None)
  -g GAIN, --gain GAIN  front end gain (dB) (default: None)
  -a, --agc             enable AGC (default: False)
  --iq-swap             swap IQ signals (default: False)
  --biastee             enable bias tee (default: False)
  --digital-agc         enable digital AGC (default: False)
  --offset-tune         enable offset tune (default: False)
  --direct-samp DIRECT_SAMP
                        select I or Q channel: 1 or 2 (default: None)
  --pcm16               write 16-bit PCM samples (default: False)
  --rf64                write RF64 file (default: False)
  --notimestamp         do not append timestamp to output file name (default:
                        False)
  --pause               pause recording (default: False)
  --output OUTPUT       output file name (default: output)
  --packet-size PACKET_SIZE
                        packet size in bytes (default: 1024)
  --buffer-size BUFFER_SIZE
                        buffer size in MB (default: 256)
  --hostname HOSTNAME   REST server hostname (default: 0.0.0.0)
  --port PORT           REST server port number (default: 8080)
  --refresh REFRESH     peak meter refresh (sec) (default: 2)
  --quiet               do not print peak values (default: False)
```


## REST API

The REST API is available off port 8080.  Use POST or PUT to change
a program or radio setting.  Use GET to view it.  If a boolean is needed, the following
strings are accepted: y, n, yes, no, true, and false.  Unpausing the stream creates
a new output file.   If the option --notimestamp is enabled, this means any previously existing
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


