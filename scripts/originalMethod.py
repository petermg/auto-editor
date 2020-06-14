'''scripts/originalMethod.py'''

import pydub
import numpy as np
from scipy.io import wavfile

import os
import sys
import math
import subprocess
from re import search
from multiprocessing import Process
from shutil import move, rmtree

from scripts.originalAudio import handleAudio, splitAudio
from scripts.originalVid import splitVideo

TEMP = '.TEMP'
CACHE = '.CACHE'

def getZooms(chunks, audioFrameCount, hasLoudAudio, FRAME_SPREADAGE):
    zooms = {}
    shouldIncludeFrame = np.zeros((audioFrameCount))
    hold = False
    endZoom = 0
    wait = ''
    for i in range(audioFrameCount):
        if(i in zooms):
            continue
        start = int(max(0, i-FRAME_SPREADAGE))
        end = int(min(audioFrameCount, i+1+FRAME_SPREADAGE))
        shouldIncludeFrame[i] = np.max(hasLoudAudio[start:end])
        if(i >= 2 and shouldIncludeFrame[i] == 2 and not hold):
            if(shouldIncludeFrame[i] != shouldIncludeFrame[i-1]):
                a = 1.2 - 1.0 # 1.0 -> 1.2
                p = int(frameRate / 3)
                for x in range(1, p + 1):
                    trans = a * math.sin((math.pi/(2*p)) * x + (2*math.pi))
                    zooms[i+x-3] = 1 + trans
                hold = True
                endZoom = i + x
                continue
        if(hold):
            zooms[i-1] = 1.2
            if(len(shouldIncludeFrame) - i > int(frameRate * 1.5) and
                shouldIncludeFrame[i] == 1 and i-endZoom > int(frameRate/2)):
                for chunk in chunks:
                    if chunk[0] == i and chunk[2] == 1:
                        hold = False
    return zooms


def getMaxVolume(s):
    maxv = float(np.max(s))
    minv = float(np.min(s))
    return max(maxv, -minv)


def formatAudio(INPUT_FILE, outputFile, sampleRate, bitrate, VERBOSE=False):
    cmd = ['ffmpeg', '-i', INPUT_FILE, '-b:a', bitrate, '-ac', '2', '-ar', str(sampleRate),
     '-vn', outputFile]
    if(not VERBOSE):
        cmd.extend(['-nostats', '-loglevel', '0'])
    subprocess.call(cmd)


def formatForPydub(INPUT_FILE, outputFile, SAMPLE_RATE):
    cmd = ['ffmpeg', '-i', INPUT_FILE, '-vn', '-ar', str(SAMPLE_RATE), '-ac', '2',
    '-ab', '192k', '-f', 'mp3', outputFile, '-nostats', '-loglevel', '0']
    subprocess.call(cmd)


def getFrameRate(path):
    process = subprocess.Popen(['ffmpeg', '-i', path],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout, __ = process.communicate()
    output = stdout.decode()
    matchDict = search(r"\s(?P<fps>[\d\.]+?)\stbr", output).groupdict()
    return float(matchDict["fps"])


def originalMethod(INPUT_FILE, OUTPUT_FILE, givenFPS, FRAME_SPREADAGE, FRAME_QUALITY,
    SILENT_THRESHOLD, LOUD_THRESHOLD, SAMPLE_RATE, SILENT_SPEED, VIDEO_SPEED, KEEP_SEP,
    BACK_MUS, BACK_VOL, NEW_TRAC, BASE_TRAC, COMBINE_TRAC, VERBOSE, PRERUN, HWACCEL):

    NEW_SPEED = [SILENT_SPEED, VIDEO_SPEED]

    dotIndex = INPUT_FILE.rfind('.')
    extension = INPUT_FILE[dotIndex:]
    if(len(OUTPUT_FILE) >= 1):
        outFile = OUTPUT_FILE
    else:
        if(extension == '.m4a'):
            outFile = INPUT_FILE[:dotIndex]+'_ALTERED.wav'
        else:
            outFile = INPUT_FILE[:dotIndex]+'_ALTERED'+extension

    audioOnly = extension in ['.wav', '.mp3', '.m4a']

    if(not os.path.isfile(INPUT_FILE)):
        print('Could not find file:', INPUT_FILE)
        sys.exit()

    try:
        os.mkdir(TEMP)
    except OSError:
        rmtree(TEMP)
        os.mkdir(TEMP)

    if(audioOnly):
        if(givenFPS is None):
            frameRate = 30
        else:
            frameRate = givenFPS
    else:
        try:
            frameRate = getFrameRate(INPUT_FILE)
        except AttributeError:
            print('Warning! frame rate detection failed.')
            print('If your video has a variable frame rate, ignore this message.')
            # convert frame rate to 30 or a user defined value
            if(givenFPS is None):
                frameRate = 30
            else:
                frameRate = givenFPS

            cmd = ['ffmpeg', '-i', INPUT_FILE, '-filter:v', f'fps=fps={frameRate}',
                TEMP+'/constantVid'+extension, '-hide_banner']
            if(not VERBOSE):
                cmd.extend(['-nostats', '-loglevel', '0'])
            subprocess.call(cmd)
            INPUT_FILE = TEMP+'/constantVid'+extension

    fileSize = os.stat(INPUT_FILE).st_size

    # make Cache folder
    SKIP = False
    try:
        os.mkdir(CACHE)
    except OSError:
        if(os.path.isfile(f'{CACHE}/cache.txt')):
            file = open(f'{CACHE}/cache.txt', 'r')
            x = file.read().splitlines()
            if(x[:4] == [INPUT_FILE, str(frameRate), str(fileSize), str(FRAME_QUALITY)]
                and x[5] == str(COMBINE_TRAC)):
                print('Using cache.')
                SKIP = True
                tracks = int(x[4])
            file.close()
        if(not SKIP):
            rmtree(CACHE)
            os.mkdir(CACHE)

    if(not SKIP):
        if(audioOnly):
            print('Formatting audio.')
            formatAudio(INPUT_FILE, f'{CACHE}/0.wav', SAMPLE_RATE, '160k', VERBOSE)
            tracks = 1
        else:
            # Videos can have more than one audio track os we need to extract them all
            print('Separating audio from video.')

            tracks = 0

            cmd = ['ffprobe', INPUT_FILE, '-hide_banner', '-loglevel', 'panic',
                '-show_entries', 'stream=index', '-select_streams', 'a', '-of',
                'compact=p=0:nk=1']

            process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT)
            stdout, __ = process.communicate()
            output = stdout.decode()
            numbers = output.split('\n')
            try:
                test = int(numbers[0])
                tracks = len(numbers)-1
            except ValueError:
                print('Warning: ffprobe had an invalid output.')
                tracks = 1

            if(BASE_TRAC >= tracks):
                print("Error: You choose a track that doesn't exist.")
                print(f'There are only {tracks} tracks. (starting from 0)')
                sys.exit()
            for trackNumber in range(tracks):
                cmd = ['ffmpeg']
                if(HWACCEL is not None):
                    cmd.extend(['-hwaccel', HWACCEL])
                cmd.extend(['-i', INPUT_FILE, '-map', f'0:a:{trackNumber}',
                    f'{CACHE}/{trackNumber}.wav'])
                if(not VERBOSE):
                    cmd.extend(['-nostats', '-loglevel', '0'])
                subprocess.call(cmd)

            if(COMBINE_TRAC):
                for i in range(tracks):
                    if(i == 0):
                        allAuds = AudioSegment.from_file(f'{CACHE}/{i}.wav')
                    else:
                        newTrack = AudioSegment.from_file(f'{CACHE}/{i}.wav')
                        allAuds = allAuds.overlay(newTrack)
                allAuds.export(f'{CACHE}/my0.wav', format='wav')
                os.rename(f'{CACHE}/my0.wav', f'{CACHE}/0.wav')
                tracks = 1
            print(f'Done with audio. ({tracks} tracks)')

            # now deal with the video (this takes longer)
            print('Splitting video into jpgs. (This can take a while)')
            cmd = ['ffmpeg']
            if(HWACCEL is not None):
                cmd.extend(['-hwaccel', HWACCEL])
            cmd.extend(['-i', INPUT_FILE, '-qscale:v', str(FRAME_QUALITY),
                f'{CACHE}/frame%06d.jpg'])
            if(not VERBOSE):
                cmd.extend(['-nostats', '-loglevel', '0'])
            subprocess.call(cmd)

    if(PRERUN):
        file = open(f'{CACHE}/cache.txt', 'w')
        file.write(f'{INPUT_FILE}\n{frameRate}\n{fileSize}\n{FRAME_QUALITY}\n{tracks}\n{COMBINE_TRAC}\n')
        print('Done.')
        sys.exit()

    # calculating chunks.
    if(NEW_TRAC is None):
        # always base cuts by the first track
        sampleRate, audioData = wavfile.read(CACHE+'/'+str(BASE_TRAC)+'.wav')
    else:
        formatAudio(NEW_TRAC, f'{TEMP}/NEW_TRAC.wav', SAMPLE_RATE, '160k', VERBOSE)
        sampleRate, audioData = wavfile.read(f'{TEMP}/NEW_TRAC.wav')
    audioSampleCount = audioData.shape[0]
    maxAudioVolume = getMaxVolume(audioData)

    samplesPerFrame = sampleRate / frameRate
    audioFrameCount = int(math.ceil(audioSampleCount / samplesPerFrame))
    hasLoudAudio = np.zeros((audioFrameCount))

    for i in range(audioFrameCount):
        start = int(i * samplesPerFrame)
        end = min(int((i+1) * samplesPerFrame), audioSampleCount)
        audiochunks = audioData[start:end]
        maxchunksVolume = getMaxVolume(audiochunks) / maxAudioVolume
        if(maxchunksVolume >= LOUD_THRESHOLD):
            hasLoudAudio[i] = 2
        elif(maxchunksVolume >= SILENT_THRESHOLD):
            hasLoudAudio[i] = 1

    chunks = [[0, 0, 0]]
    shouldIncludeFrame = np.zeros((audioFrameCount))
    for i in range(audioFrameCount):
        start = int(max(0, i-FRAME_SPREADAGE))
        end = int(min(audioFrameCount, i+1+FRAME_SPREADAGE))
        shouldIncludeFrame[i] = min(1, np.max(hasLoudAudio[start:end]))

        if (i >= 1 and shouldIncludeFrame[i] != shouldIncludeFrame[i-1]):
            chunks.append([chunks[-1][1], i, shouldIncludeFrame[i-1]])

    chunks.append([chunks[-1][1], audioFrameCount, shouldIncludeFrame[i-1]])
    chunks = chunks[1:]

    if(audioOnly):
        splitAudio(TEMP+'/audioNew.wav', chunks, samplesPerFrame, NEW_SPEED, audioData,
            SAMPLE_RATE, maxAudioVolume)
    else:
        zooms = getZooms(chunks, audioFrameCount,
            hasLoudAudio, FRAME_SPREADAGE)

        p1 = Process(target=handleAudio, args=(tracks, chunks, samplesPerFrame, NEW_SPEED,
            maxAudioVolume))
        p1.start()
        p2 = Process(target=splitVideo, args=(chunks, NEW_SPEED, frameRate, zooms,
            samplesPerFrame, SAMPLE_RATE, audioData, extension, VERBOSE))
        p2.start()

        p1.join()
        p2.join()

    if(BACK_MUS is not None):
        formatForPydub(f'{TEMP}/new{BASE_TRAC}.wav', TEMP+'/output.mp3', SAMPLE_RATE)

        vidSound = AudioSegment.from_file(TEMP+'/output.mp3')

        back = AudioSegment.from_file(BACK_MUS)
        if(len(back) > len(vidSound)):
            back = back[:len(vidSound)]

        def match_target_amplitude(back, vidSound, target):
            diff = back.dBFS - vidSound.dBFS
            change_in_dBFS = target - diff
            return back.apply_gain(change_in_dBFS)

        # fade the background music out by 1 second
        back = match_target_amplitude(back, vidSound, BACK_VOL).fade_out(1000)
        #combined = vidSound.overlay(back)
        print('exporting background music')
        back.export(f'{TEMP}/new{tracks}.wav', format='wav')

        if(not os.path.isfile(f'{TEMP}/new{tracks}.wav')):
            raise IOError(f'The new music audio file was not created.')

        tracks += 1

    if(audioOnly):
        print('Moving audio.')
        move(f'{TEMP}/audioNew.wav', outFile)
    else:
        print('Finishing video.')

        if(KEEP_SEP):
            cmd = ['ffmpeg', '-y']
            if(HWACCEL is not None):
                cmd.extend(['-hwaccel', HWACCEL])
            for i in range(tracks):
                cmd.extend(['-i', f'{TEMP}/new{i}.wav'])
            cmd.extend(['-i', TEMP+'/output'+extension]) # add input video
            for i in range(tracks):
                cmd.extend(['-map', f'{i}:a:0'])
            cmd.extend(['-map', f'{tracks}:v:0','-c:v', 'copy', '-movflags', '+faststart',
                outFile])
            if(not VERBOSE):
                cmd.extend(['-nostats', '-loglevel', '0'])
        else:
            # downmix the audio tracks
            # example command:
            # ffmpeg -i 0.mp3 -i 1.mp3 -filter_complex amerge=inputs=2 -ac 2 out.mp3
            if(tracks > 1):
                cmd = ['ffmpeg']
                for i in range(tracks):
                    cmd.extend(['-i', f'{TEMP}/new{i}.wav'])
                cmd.extend(['-filter_complex', f'amerge=inputs={tracks}', '-ac', '2',
                    f'{TEMP}/newAudioFile.wav'])
                if(not VERBOSE):
                    cmd.extend(['-nostats', '-loglevel', '0'])
                subprocess.call(cmd)
            else:
                os.rename(f'{TEMP}/new0.wav', f'{TEMP}/newAudioFile.wav')

            cmd = ['ffmpeg', '-y']
            if(HWACCEL is not None):
                cmd.extend(['-hwaccel', HWACCEL])
            cmd.extend(['-i', f'{TEMP}/newAudioFile.wav'])
            cmd.extend(['-i', f'{TEMP}/output{extension}']) # add input video
            cmd.extend(['-c:v', 'copy', '-movflags', '+faststart', outFile])
            if(not VERBOSE):
                cmd.extend(['-nostats', '-loglevel', '0'])
        subprocess.call(cmd)

    # reset cache folder
    if(not audioOnly):
        with open(f'{TEMP}/Renames.txt', 'r') as f:
            renames = f.read().splitlines()
            for i in range(0, len(renames), 2):
                os.rename(renames[i+1], renames[i])

    # create cache check with vid stats
    if(BACK_MUS is not None):
        tracks -= 1
    file = open(f'{CACHE}/cache.txt', 'w')
    file.write(f'{INPUT_FILE}\n{frameRate}\n{fileSize}\n{FRAME_QUALITY}\n{tracks}\n{COMBINE_TRAC}\n')

    return outFile