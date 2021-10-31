

# rfsoapyfile

A Python 3 script for capturing and recording a SDR stream to a WAV file (or serving it as a HTTP audio stream).
The script is threaded for high performance, especially
on a Raspberry Pi.  The script includes a REST API
for controlling the capture and WAV recording remotely.

The script will save the WAV stream in either the RF64 or WAV(32) file format.
By default the recording is saved in the WAV(32) format using 32-bit IEEE floating point PCM samples.
To save using 16-bit PCM samples use the --pcm16 option.
The SDR specific 'auxi' 
metadata chunk, with record time and center frequency information, is added to the WAV audio file as well.

To quit the script and close the recording type control-C, or use the /quit REST call.


## Dependencies

The script requires the numpy and SoapySDR Python libraries.

## Example

```
$ python3 soapyfile.py -f 100.1e6 -r 1e6 --pcm16 -g 42 --output out --pause
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
strings are accepted: y, n, yes, no, true, and false.  Pausing the recording closes the WAV output file, while unpausing the recording creates
a new output file.   If the option --notimestamp is enabled, this means any previously existing
output file of the same name will be overwritten.

```
PUT /quit              <bool>      stop capture and terminate program, yes or no
PUT /rate              <float>     set sampling rate (Hz) when recording paused
PUT /frequency         <float>     set center frequency (Hz)
PUT /gain              <float>     set gain (dB)
PUT /agc               <bool>      enable agc, yes or no
PUT /pause             <bool>      pause recording, yes or no
PUT /setting/<name>    <string>    change named soapy setting

GET /rate              return sampling rate (Hz)
GET /frequency         return center frequency (Hz)
GET /gain              return gain (Hz)
GET /agc               return AGC setting (yes or no)
GET /peak              return the latest ADC peak value (dBFS)
GET /pause             return whether the recording is paused (yes or no)
GET /setting           return list of available soapy setting names and their values
GET /setting/<name>    return value of named soapy setting

GET /s16               return a 16-bit integer PCM WAV HTTP audio stream
GET /f32               return a 32-bit floating point PCM WAV HTTP audio stream
```

Here are some sample curl commands:

```
curl localhost:8080/f32 --output out.wav
curl -d yes localhost:8080/agc
curl -d yes localhost:8080/quit
curl -d yes localhost:8080/pause
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
$ curl localhost:8080/setting
direct_samp: 0
offset_tune: false
iq_swap: false
digital_agc: false
biastee: false
```

```
$ curl -i localhost:8080/f32 
HTTP/1.1 200 OK
Server: BaseHTTP/0.6 Python/3.7.3
Date: Sun, 31 Oct 2021 15:11:10 GMT
Transfer-Encoding: chunked
Content-Type: audio/wav

Warning: Binary output can mess up your terminal. Use "--output -" to tell 
Warning: curl to output it to your terminal anyway, or consider "--output 
Warning: <FILE>" to save to a file.
```

## Benchmarks

My Raspberry Pi 3A+ is able to support up to a 1.5MB sample rate with the RTLSDR before it overflows.  Here is the core usage:

![htop command](res/pi3aplus.png)

While my Raspberry Pi 4B is able to support up to a 1.6MB sample rate with the RTLSDR.

![htop command](res/pi4b.png)

The Raspberry Pi Zero W Version 1 only has one core, so threading does not help.
Version 2 of the Zero has five cores, however, but I do not have one to test against.

