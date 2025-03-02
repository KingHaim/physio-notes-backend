from flask import Flask, request, jsonify
import speech_recognition as sr
import requests
import os
import uuid
import tempfile
import logging
from flask_cors import CORS
from dotenv import load_dotenv
from threading import Lock

# Initialize Flask app
app = Flask(__name__)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define allowed origins for CORS
ALLOWED_ORIGINS = [
    "http://localhost:5173",              # Local development
    "https://physio-notes-frontend.onrender.com",  # Render frontend (if applicable)
    "https://physio-notes-app.vercel.app"  # Vercel production
]

# Configure CORS
CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}})

# Thread-safe session storage
recording_sessions = {}
session_lock = Lock()

def transcribe_audio(audio_path, language):
    """Transcribe audio file with a 30-second limit."""
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(audio_path) as source:
            audio = recognizer.record(source, duration=30)
        transcription = recognizer.recognize_google(audio, language=language)
        logger.info(f"Transcription successful: {transcription[:50]}...")
        return transcription
    except sr.UnknownValueError:
        logger.warning("Transcription failed: Could not understand audio")
        return "Could not understand audio"
    except sr.RequestError as e:
        logger.error(f"Transcription error: {e}")
        return f"Transcription error: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in transcription: {e}")
        return f"Error: {str(e)}"

def generate_physio_notes(transcription, api_key):
    """Generate SOAP notes using DeepSeek API."""
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    prompt = f"""
    You are an expert physiotherapy assistant. Based on the following transcript from a physiotherapy session, 
    generate structured patient notes in SOAP format (Subjective, Objective, Assessment, Plan). Extract key 
    details like patient complaints, physical findings, assessment insights, and treatment plans. The 
    transcript may be in English or Spanish—process accordingly and provide notes in English.

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
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()["choices"][0]["message"]["content"]
        logger.info("Notes generated successfully")
        return result
    except requests.RequestException as e:
        logger.error(f"DeepSeek API error: {e}")
        return f"Error: {str(e)}"

@app.route('/start_recording', methods=['POST'])
def start_recording():
    """Start a new recording session."""
    language = request.form.get('language', 'en-US')
    session_id = str(uuid.uuid4())  # Generate unique session ID
    with session_lock:
        recording_sessions[session_id] = {'language': language, 'chunks': []}
    logger.info(f"Session started: {session_id} with language {language}")
    return jsonify({"message": "Recording started", "session_id": session_id})

@app.route('/stop_recording', methods=['POST'])
def stop_recording():
    """Stop recording and process audio."""
    session_id = request.form.get('session_id')
    if not session_id or session_id not in recording_sessions:
        logger.warning(f"Invalid or missing session_id: {session_id}")
        return jsonify({"error": "Invalid or missing session ID"}), 400

    audio_file = request.files.get('audio')
    if not audio_file:
        logger.error(f"No audio file provided for session: {session_id}")
        return jsonify({"error": "No audio file provided"}), 400

    try:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            audio_file.save(temp_file.name)
            logger.info(f"Audio saved: {temp_file.name}, size: {os.path.getsize(temp_file.name)} bytes")
            
            with session_lock:
                language = recording_sessions[session_id]['language']
                session_data = recording_sessions.pop(session_id)  # Clean up session

            transcription = transcribe_audio(temp_file.name, language)
            api_key = os.getenv("DEEPSEEK_API_KEY", "your-default-key-here")
            notes = generate_physio_notes(transcription, api_key)

        os.unlink(temp_file.name)  # Clean up temporary file
        logger.info(f"Session {session_id} processed and cleaned up")
        return jsonify({
            "transcription": transcription,
            "notes": notes,
            "audio_url": f"https://example.com/audio_{session_id}.wav"  # Placeholder URL
        })
    except Exception as e:
        logger.error(f"Error processing stop_recording for session {session_id}: {e}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)