from flask import Flask, request, jsonify
import speech_recognition as sr
import requests
import os
import threading
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env

app = Flask(__name__)
# Allow requests from local development, Render frontend, and Vercel frontend
CORS(app, resources={
    r"/start_recording": {"origins": ["http://localhost:5173", "https://physio-notes-frontend.onrender.com", "https://physio-notes-app.vercel.app"]},
    r"/stop_recording": {"origins": ["http://localhost:5173", "https://physio-notes-frontend.onrender.com", "https://physio-notes-app.vercel.app"]},
    r"/transcribe": {"origins": ["http://localhost:5173", "https://physio-notes-frontend.onrender.com", "https://physio-notes-app.vercel.app"]},
    r"/generate_notes": {"origins": ["http://localhost:5173", "https://physio-notes-frontend.onrender.com", "https://physio-notes-app.vercel.app"]}
})

recording_sessions = {}  # Store session data for continuous recording

def transcribe_audio(audio_file, language):
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_file) as source:
        audio = recognizer.record(source, duration=30)  # Limit to 30 seconds
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
    recording_sessions[session_id] = {'language': language, 'chunks': []}
    return jsonify({"message": "Recording started", "session_id": session_id})

@app.route('/stop_recording', methods=['POST'])
def stop_recording():
    session_id = request.form.get('session_id', 'default_session')
    if session_id not in recording_sessions:
        print(f"No active session for {session_id}, creating mock session for testing")
        recording_sessions[session_id] = {'language': 'en-US', 'chunks': []}  # Mock session
    audio_file = request.files['audio']
    if audio_file:
        filename = f"session_{session_id}.wav"
        audio_file.save(filename)
        print(f"Received audio file: {filename}, size: {os.path.getsize(filename)} bytes")
        language = recording_sessions[session_id]['language']
        transcription = transcribe_audio(filename, language)
        api_key = os.getenv("DEEPSEEK_API_KEY", "sk-dc7c41ed769b4d0f9757b9b6b82158d7")
        notes = generate_physio_notes(transcription, api_key)
        os.remove(filename)
        del recording_sessions[session_id]
        return jsonify({"transcription": transcription, "notes": notes, "audio_url": f"https://example.com/audio_{session_id}.wav"})
    return jsonify({"error": "No audio file provided"}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)