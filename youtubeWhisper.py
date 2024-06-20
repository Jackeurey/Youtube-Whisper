import subprocess
import os
import pysubs2
from pydub import AudioSegment
import whisperx
import re
from os.path import exists
import argparse
from pathlib import Path

AudioSegment.converter = "ffmpeg.exe"

def run_yt_dlp(link, output_dir, take_subs):
	sub_args = ""
	if take_subs:
		sub_args = "--sub-langs ja --write-subs --sub-format srt"

	subprocess.check_call(f'yt-dlp --yes-playlist {sub_args} --paths {output_dir} {link}', shell=True)

def subs_exist(path, name):
	sub_types = ['ja.vtt', 'ja.srt']
	return any([os.path.exists(os.path.join(path, f'{name}.{sub_ext}')) for sub_ext in sub_types])

def audio_exists(path, name):
	file = os.path.join(path,f'{name}.mp3')
	return os.path.exists(file)

def transcribe(model, audio):
	result = model.transcribe(audio, 
			chunk_size=5, 
			print_progress=False)
	return pysubs2.load_from_whisper(result)

def load_subs(path, name):
	sub_types = ['ja.vtt', 'ja.srt']
	# yt_dlp's downloaded subtitle format is inconsistent.  
	for ext in sub_types:
		file = os.path.join(path,f'{name}.{ext}')
		if os.path.exists(file):
			return pysubs2.load(file,encoding="utf-8")

def extract_audio_track(video):
	output_file_name="output.webm"
	
	ffmpeg_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'utils\\ffmpeg\\ffmpeg.exe')
	
	cmd = f'"{ffmpeg_dir}" -y -i "{video}" -map a:0 -c copy {output_file_name}'

	# Uses ffmpeg to extract the audio track and copy it in the same directory.
	subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

	# It is easier to work with pydub so I use ffmpeg to output a file, load that file into pydub, and then delete it. 
	track_audio = AudioSegment.from_file(output_file_name, 'webm')
	os.remove(output_file_name)
	return track_audio

def condenced_audio(video, subs):
	track_audio = extract_audio_track(video)
	audio = AudioSegment.empty()

	# Basic algorithm that pads the subtitle time and makes sure the sine waves of adjacent clips line up for smooth listening experience. 
	prev_end = 0
	for sub in subs:
		# Offset and fade are "magic numbers" that I obtained through trial and error. they 'feel' the smoothest to me.
		offset  = 200
		fade    = 75

		#Adds the padding off offset 
		start   = sub.start - offset
		end     = sub.end + offset
		
		# This is mostly a case dealing with the first run. As before anything is added to condensed audio, it is 0
		if fade > len(audio):
			fade = 0
		# If the offset causes an overlap of audio just make them "one clip" to avoid audio doubling
		if start - fade < prev_end + fade:
			start = prev_end
		#creates the audio segment
		segment = track_audio[start:end]
		
		#If the audio clips is less than the fade just skip it.
		if fade >= len(segment):
			continue

		# The cross fade is super important, without it their will be a pop inbetween the clips due to the sine waves not matching between adjacent clips
		audio = audio.append(segment,crossfade=fade)
		prev_end = end
	return audio

if __name__ == "__main__":
	
	parser = argparse.ArgumentParser()
	parser.add_argument('--link', 
						help='Link to video or playlist')
	parser.add_argument('--path', required=True,
						 help='Output path for video(s)')
	parser.add_argument('--take-subs', action='store_true',
						 help='Takes sub from the youtube video instead of generating them with whisperx')
	parser.add_argument('--skip-audio', action='store_true',
						 help='Skips the audio condensing')
	parser.add_argument('--compute_type', default='float32',
						help='Sets compute_type for whisperx')
	parser.add_argument('--language', default='ja',
						help='The language whisperx will use to generate subtitles')

	args = parser.parse_args()
	
	output_dir = Path(f'{args.path}')
	link = args.link
	take_subs = args.take_subs
	skip_audio = args.skip_audio
	compute_type = args.compute_type
	language = args.language
	

	if not exists(output_dir):
		os.mkdir(output_dir)

	# Get Youtube videos
	run_yt_dlp(link, output_dir, take_subs)
	
	# Whisperx
	model = whisperx.load_model('large-v3', 'cpu', 
		compute_type=compute_type,
		language=language
		)

	videos = [os.path.join(output_dir, video_file) for video_file in os.listdir(output_dir) if video_file.endswith(('.webm', '.mkv')) ]
	progres_counter = 0
	print() # Spacing for terminal output
	for video in videos:
		name = os.path.splitext(video)[0]
		
		progres_counter += 1
		print(f'{progres_counter}/{len(videos)}: {name}')

		if subs_exist(output_dir, name):
			print(f'Subtitles exist for {name} skiping...')
		else:
			print(f'Generating subtitles for {name}...')
			audio = whisperx.load_audio(video)
			subs = transcribe(model, audio)
			subs.save(os.path.join(output_dir,f'{name}.ja.srt'),
				encoding='UTF-8',
				format='srt')

		if skip_audio:
			continue
		elif audio_exists(output_dir, name):
			print(f'Condensed audio exist for {name} skiping...')
		else:
			print(f'Generating condensed audio for {name}...')
			audio = condenced_audio(video, load_subs(output_dir, name))
			audio.export(out_f = os.path.join(output_dir, f'{name}.mp3'), format='mp3')
		print() # Spacing for terminal output