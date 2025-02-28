from flask import Flask, request, jsonify
import pyaudio
import wave
import speech_recognition as sr
import requests
import os
import threading
from flask_cors import CORS
from dotenv import load_dotenv
import os

load_dotenv()  # Load environment variables from .env

app = Flask(__name__)
CORS(app, resources={r"/start_recording": {"origins": "*"}, r"/stop_recording": {"origins": "*"}})

# Audio recording setup
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

p = pyaudio.PyAudio()
recording_streams = {}  # Store streams for each session

def record_audio_continuously(session_id, stop_event, filename="session.wav"):
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    frames = []
    recording_streams[session_id] = stream
    
    try:
        while not stop_event.is_set():
            data = stream.read(CHUNK)
            frames.append(data)
    except Exception as e:
        print(f"Recording error: {e}")
    finally:
        stream.stop_stream()
        stream.close()
    
    wf = wave.open(filename, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(p.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()
    del recording_streams[session_id]
    return filename

def transcribe_audio(audio_file, language):
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_file) as source:
        audio = recognizer.record(source)
    try:
        transcription = recognizer.recognize_google(audio, language=language)
        return transcription
    except sr.UnknownValueError:
        return "Could not understand audio"
    except sr.RequestError as e:
        return f"Transcription error: {e}"

def generate_physio_notes(transcription, api_key):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    prompt = f"""
    You are an expert physiotherapy assistant. Based on the following conversation transcript from a physiotherapy session, generate structured patient notes in SOAP format (Subjective, Objective, Assessment, Plan). Extract key details like patient complaints, physical findings, assessment insights, and treatment plans. The transcript may be in English or Spanish—process it accordingly and provide notes in English.

    Transcript: "{transcription}"
    """
    data = {
        "model": "deepseek-reasoner",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }

    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        result = response.json()["choices"][0]["message"]["content"]
        return result
    else:
        return f"Error: {response.status_code} - {response.text}"

@app.route('/start_recording', methods=['POST'])
def start_recording():
    language = request.form.get('language', 'en-US')
    session_id = request.form.get('session_id', 'default_session')
    stop_event = threading.Event()
    
    # Start recording in a separate thread
    t = threading.Thread(target=record_audio_continuously, args=(session_id, stop_event, f"session_{session_id}.wav"))
    t.daemon = True
    t.start()
    
    return jsonify({"message": "Recording started", "session_id": session_id})

@app.route('/stop_recording', methods=['POST'])
def stop_recording():
    session_id = request.form.get('session_id', 'default_session')
    if session_id in recording_streams:
        stop_event = threading.Event()
        stop_event.set()  # Signal to stop recording
        filename = f"session_{session_id}.wav"
        
        # Wait briefly for the recording thread to finish
        time.sleep(1)  # Adjust if needed
        
        # Transcribe and generate notes
        language = request.form.get('language', 'en-US')
        api_key = "sk-dc7c41ed769b4d0f9757b9b6b82158d7"  # Replace with your actual DeepSeek API key
        
        transcription = transcribe_audio(filename, language)
        notes = generate_physio_notes(transcription, api_key)
        
        os.remove(filename)  # Clean up the audio file
        return jsonify({"transcription": transcription, "notes": notes})
    return jsonify({"error": "No active recording for this session"}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)

# Cleanup on exit
def cleanup():
    global p
    for stream in recording_streams.values():
        if stream.is_active():
            stream.stop_stream()
            stream.close()
    p.terminate()

import atexit
import time
atexit.register(cleanup)