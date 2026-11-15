import React,{ useEffect, useRef, useState } from "react";
import {
  Brain, FileText, Target, Upload, CheckCircle2, Mic, MicOff,
  Volume2, LoaderCircle, Sparkles, AlertCircle, RefreshCw,
  ArrowRight, Check, Square, Play, Headphones
} from "lucide-react";

// Change this if your FastAPI server runs at another address.
const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

function App() {
  const [resume, setResume] = useState(null);
  const [jobDescription, setJobDescription] = useState("");
  const [screen, setScreen] = useState("create"); // create | interview | complete
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [interviewId, setInterviewId] = useState("");
  const [totalQuestions, setTotalQuestions] = useState(0);
  const [question, setQuestion] = useState(null);
  const [voiceState, setVoiceState] = useState("idle");
  const [transcription, setTranscription] = useState("");
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [lastSaved, setLastSaved] = useState(false);

  const fileInputRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);

  useEffect(() => {
    if (voiceState !== "recording") return;
    timerRef.current = window.setInterval(
      () => setRecordingSeconds((seconds) => seconds + 1),
      1000
    );
    return () => window.clearInterval(timerRef.current);
  }, [voiceState]);

  useEffect(() => {
    return () => {
      window.speechSynthesis?.cancel();
      if (timerRef.current) window.clearInterval(timerRef.current);
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const formatTime = (seconds) =>
    `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

  const stopStream = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  };

  async function createInterview(event) {
    event.preventDefault();
    setError("");

    if (!resume) {
      setError("Please choose your resume PDF.");
      return;
    }
    if (!jobDescription.trim()) {
      setError("Please enter the job description.");
      return;
    }

    const form = new FormData();
    form.append("file", resume);
    form.append("job_description", jobDescription.trim());

    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/upload-resume/`, {
        method: "POST",
        body: form
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not create interview.");

      if (!data.interview_id) throw new Error("The server did not return an interview ID.");

      setInterviewId(data.interview_id);
      setTotalQuestions(data.total_questions || 0);
      setScreen("interview");
      await fetchNextQuestion(data.interview_id);
    } catch (err) {
      setError(err.message || "Something went wrong while creating the interview.");
    } finally {
      setLoading(false);
    }
  }

  async function fetchNextQuestion(id = interviewId) {
    setError("");
    setVoiceState("loading");
    setTranscription("");
    setLastSaved(false);

    try {
      const response = await fetch(
        `${API_BASE}/interview/${encodeURIComponent(id)}/next-question`
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not fetch the next question.");

      if (data.completed) {
        window.speechSynthesis?.cancel();
        setQuestion(null);
        setVoiceState("idle");
        setScreen("complete");
        return;
      }

      if (!data.question_id || !data.question) {
        throw new Error("The question response is missing question_id or question.");
      }

      setQuestion(data);
      setVoiceState("ready");
      // Speak after the question has rendered. Candidate starts recording manually.
      window.setTimeout(() => speakQuestion(data.question), 250);
    } catch (err) {
      setVoiceState("error");
      setError(err.message || "Could not load the next question.");
    }
  }

  function speakQuestion(text) {
    if (!("speechSynthesis" in window)) {
      setVoiceState("ready");
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    utterance.rate = 0.92;
    utterance.onstart = () => setVoiceState("speaking");
    utterance.onend = () => setVoiceState("ready");
    utterance.onerror = () => setVoiceState("ready");
    window.speechSynthesis.speak(utterance);
  }

  async function startRecording() {
    setError("");
    setTranscription("");
    setRecordingSeconds(0);

    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setError("Audio recording is not supported in this browser. Try the latest Chrome or Edge.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const preferredTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/ogg;codecs=opus",
        "audio/mp4"
      ];
      const mimeType = preferredTypes.find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);

      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        setError("There was a problem recording audio. Please try again.");
        setVoiceState("ready");
        stopStream();
      };
      recorder.onstop = async () => {
        const actualType = recorder.mimeType || mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type: actualType });
        stopStream();
        if (blob.size === 0) {
          setVoiceState("ready");
          setError("No audio was recorded. Please try again.");
          return;
        }
        await uploadAnswer(blob, actualType);
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setVoiceState("recording");
    } catch (err) {
      setVoiceState("ready");
      setError(err.name === "NotAllowedError"
        ? "Microphone permission was denied. Allow microphone access and try again."
        : "Could not access your microphone.");
    }
  }

  function stopRecording() {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      setVoiceState("processing");
      recorder.stop();
    }
  }

  async function uploadAnswer(blob, mimeType) {
    if (!question) return;

    const extension = mimeType.includes("ogg") ? "ogg"
      : mimeType.includes("mp4") ? "m4a" : "webm";

    const form = new FormData();
    form.append("question_id", String(question.question_id));
    form.append("audio", blob, `answer.${extension}`);

    try {
      const response = await fetch(
        `${API_BASE}/interview/${encodeURIComponent(interviewId)}/submit-audio`,
        { method: "POST", body: form }
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not submit your answer.");

      setTranscription(data.transcribed_answer || "");
      setLastSaved(Boolean(data.saved));
      setVoiceState(data.saved ? "saved" : "error");
    } catch (err) {
      setVoiceState("error");
      setError(err.message || "Audio upload failed. Please try again.");
    }
  }

  function retryCurrentQuestion() {
    window.speechSynthesis?.cancel();
    setTranscription("");
    setLastSaved(false);
    setError("");
    setVoiceState("ready");
    if (question?.question) speakQuestion(question.question);
  }

  function continueToNextQuestion() {
    fetchNextQuestion();
  }

  function resetApp() {
    window.speechSynthesis?.cancel();
    stopStream();
    setResume(null);
    setJobDescription("");
    setInterviewId("");
    setQuestion(null);
    setTranscription("");
    setError("");
    setScreen("create");
    setVoiceState("idle");
  }

  const isBusy = ["loading", "processing"].includes(voiceState);

  return (
    <div className="app-shell">
      <style>{styles}</style>

      {screen === "create" && (
        <main className="create-layout">
          <header className="brand-header">
            <div className="brand-mark"><Brain size={29} strokeWidth={2.2} /></div>
            <div>
              <h1>CareerCoach AI</h1>
              <p>Advance your career with AI-powered interview preparation</p>
            </div>
          </header>

          <div className="feature-pills" aria-label="Features">
            <span><i /> Resume-based questions</span>
            <span><i /> AI mock interview</span>
            <span><i /> Instant interview summary</span>
          </div>

          <form className="setup-grid" onSubmit={createInterview}>
            <section className="panel">
              <div className="panel-heading resume-heading">
                <div className="panel-icon blue"><FileText size={23} /></div>
                <div>
                  <h2>Upload Resume</h2>
                  <p>PDF format</p>
                </div>
              </div>
              <div className="panel-body">
                <input
                  ref={fileInputRef}
                  className="hidden-input"
                  type="file"
                  accept=".pdf,application/pdf"
                  onChange={(event) => {
                    const selected = event.target.files?.[0] || null;
                    setResume(selected);
                    setError("");
                  }}
                />
                <button
                  type="button"
                  className={`drop-zone ${resume ? "has-file" : ""}`}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {resume ? (
                    <>
                      <CheckCircle2 className="upload-success" size={48} />
                      <strong>{resume.name}</strong>
                      <span>{(resume.size / (1024 * 1024)).toFixed(2)} MB · Ready to upload</span>
                      <small>Click to choose a different file</small>
                    </>
                  ) : (
                    <>
                      <Upload className="upload-symbol" size={54} />
                      <strong>Choose your resume</strong>
                      <span>Click to browse PDF files</span>
                      <small>PDF only · Maximum size depends on server configuration</small>
                    </>
                  )}
                </button>
              </div>
            </section>

            <section className="panel">
              <div className="panel-heading jd-heading">
                <div className="panel-icon green"><Target size={23} /></div>
                <div>
                  <h2>Job Description</h2>
                  <p>Paste the job requirements</p>
                </div>
              </div>
              <div className="panel-body jd-body">
                <textarea
                  value={jobDescription}
                  onChange={(event) => setJobDescription(event.target.value)}
                  placeholder="Paste the job description here..."
                  rows={9}
                />
                <div className="jd-footer">
                  <span>{jobDescription.length} characters</span>
                  <button className="primary-button" type="submit" disabled={loading}>
                    {loading ? <LoaderCircle className="spin" size={18} /> : <Sparkles size={18} />}
                    {loading ? "Preparing interview..." : "Start Mock Interview"}
                    {!loading && <ArrowRight size={17} />}
                  </button>
                </div>
              </div>
            </section>
          </form>

          {error && <div className="error-banner"><AlertCircle size={18} />{error}</div>}
          <p className="privacy-note"><Check size={14} /> Your resume is used to prepare this interview.</p>
        </main>
      )}

      {screen === "interview" && (
        <main className="interview-layout">
          <header className="interview-brand">
            <div className="brand-mark small"><Brain size={24} /></div>
            <span>CareerCoach AI</span>
          </header>

          <section className="interview-content">
            <div className="eyebrow"><span className="live-dot" /> MOCK INTERVIEW</div>
            <h1>Let's get started.</h1>
            <p className="interview-subtitle">Listen to the question, then record your answer when you're ready.</p>

            <div className="question-card">
              <div className="question-label"><Sparkles size={16} /> YOUR QUESTION</div>
              {voiceState === "loading" ? (
                <div className="question-loading"><LoaderCircle className="spin" /> Preparing your next question...</div>
              ) : (
                <h2>{question?.question || "Loading question..."}</h2>
              )}
              {question?.category && (
                <div className="question-meta">
                  <span>{question.category}</span>
                  {question.difficulty && <span>{question.difficulty}</span>}
                </div>
              )}
            </div>

            <div className="voice-status">
              <div className={`voice-orb ${voiceState}`}>
                {voiceState === "speaking" ? <Volume2 size={29} />
                  : voiceState === "recording" ? <Mic size={29} />
                  : voiceState === "processing" || voiceState === "loading" ? <LoaderCircle className="spin" size={29} />
                  : voiceState === "saved" ? <CheckCircle2 size={29} />
                  : <Headphones size={29} />}
              </div>
              <strong>
                {voiceState === "speaking" ? "AI is speaking"
                  : voiceState === "recording" ? "You're recording"
                  : voiceState === "processing" ? "Transcribing your answer"
                  : voiceState === "loading" ? "Loading question"
                  : voiceState === "saved" ? "Answer saved"
                  : voiceState === "error" ? "Something went wrong"
                  : "Your turn to answer"}
              </strong>
              <span>
                {voiceState === "recording" ? formatTime(recordingSeconds)
                  : voiceState === "speaking" ? "Please listen to the complete question"
                  : voiceState === "saved" ? "Your response has been saved successfully"
                  : voiceState === "processing" ? "Please wait while we process your recording"
                  : "You can start recording whenever you're ready"}
              </span>
            </div>

            {voiceState === "recording" ? (
              <button className="record-button stop-button" onClick={stopRecording}>
                <Square size={17} fill="currentColor" /> Stop & submit answer
              </button>
            ) : voiceState === "saved" ? (
              <button className="primary-button next-button" onClick={continueToNextQuestion}>
                Next question <ArrowRight size={18} />
              </button>
            ) : (
              <button
                className="record-button"
                onClick={startRecording}
                disabled={!question || isBusy || voiceState === "speaking" || voiceState === "error"}
              >
                <Mic size={19} /> Start recording
              </button>
            )}

            {voiceState === "error" && (
              <button className="text-button" onClick={retryCurrentQuestion}>
                <RefreshCw size={15} /> Try this question again
              </button>
            )}

            {transcription && (
              <div className="transcription-card">
                <div><CheckCircle2 size={17} /> <strong>Transcription</strong></div>
                <p>{transcription}</p>
              </div>
            )}

            {error && <div className="error-banner"><AlertCircle size={18} />{error}</div>}
          </section>
          <p className="bottom-note">Speak clearly and take your time. Your answer is submitted when you stop recording.</p>
        </main>
      )}

      {screen === "complete" && (
        <main className="completion-layout">
          <div className="completion-icon"><CheckCircle2 size={42} /></div>
          <div className="eyebrow">INTERVIEW FINISHED</div>
          <h1>Great work!</h1>
          <p className="completion-copy">
            You've completed your mock interview. Your responses have been saved successfully.
          </p>
          <div className="completion-card">
            <div className="completion-stat">
              <span>Interview</span>
              <strong>Completed</strong>
            </div>
            <div className="completion-stat">
              <span>Questions prepared</span>
              <strong>{totalQuestions || "—"}</strong>
            </div>
          </div>
          <div className="feedback-placeholder">
            <Sparkles size={20} />
            <div>
              <strong>Your feedback will appear here</strong>
              <p>Interview feedback will be available once answer evaluation is connected.</p>
            </div>
          </div>
          <button className="primary-button" onClick={resetApp}>Start a new interview <ArrowRight size={17} /></button>
        </main>
      )}
    </div>
  );
}

const styles = `
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#172033;background:#f2f5ff;font-synthesis:none;text-rendering:optimizeLegibility}
*{box-sizing:border-box}
body{margin:0;min-width:320px;min-height:100vh}
button,textarea{font:inherit}
button{cursor:pointer}
button:disabled{opacity:.55;cursor:not-allowed}
.app-shell{min-height:100vh;background:radial-gradient(circle at 92% 14%,rgba(202,218,255,.38) 0 95px,transparent 96px),linear-gradient(125deg,#f5f7ff 0%,#eef2ff 100%);padding:42px 5.2% 36px}
.create-layout{max-width:1420px;margin:0 auto}
.brand-header{display:flex;align-items:center;gap:17px}
.brand-mark{width:62px;height:62px;border-radius:15px;display:grid;place-items:center;color:white;background:linear-gradient(140deg,#3565e9,#7b35dc);box-shadow:0 8px 18px rgba(75,85,220,.2);flex:none}
.brand-mark.small{width:46px;height:46px;border-radius:12px}
.brand-header h1{margin:0;font-size:clamp(30px,4vw,48px);line-height:1.1;font-weight:800;letter-spacing:-1.7px;background:linear-gradient(90deg,#3566e8,#7738d8);background-clip:text;color:transparent}
.brand-header p{margin:8px 0 0;color:#5f687a;font-size:17px}
.feature-pills{display:flex;gap:13px;flex-wrap:wrap;margin:29px 0 36px}
.feature-pills span{display:flex;align-items:center;gap:9px;padding:10px 17px;border-radius:30px;background:#f0f1f6;color:#6b7280;font-size:14px;font-weight:500}
.feature-pills i{width:10px;height:10px;border-radius:50%;background:#c9ccd5}
.setup-grid{display:grid;grid-template-columns:1fr 1fr;gap:32px;align-items:stretch}
.panel{background:#fff;border:1px solid #e3e7ef;border-radius:15px;overflow:hidden;box-shadow:0 8px 18px rgba(26,38,68,.09)}
.panel-heading{min-height:108px;display:flex;align-items:center;gap:15px;padding:24px 28px}
.resume-heading{background:#eef2ff}
.jd-heading{background:#effbf3}
.panel-icon{width:46px;height:46px;border-radius:12px;display:grid;place-items:center;flex:none}
.panel-icon.blue{background:#dce8ff;color:#3769e8}
.panel-icon.green{background:#dcf8e6;color:#36a35a}
.panel-heading h2{font-size:19px;margin:0 0 5px;letter-spacing:-.4px}
.panel-heading p{margin:0;color:#697386;font-size:14px}
.panel-body{padding:27px 28px 29px}
.hidden-input{display:none}
.drop-zone{width:100%;min-height:270px;border:2px dashed #58bd75;border-radius:13px;background:#f2fcf5;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:12px;color:#4c9f62;padding:25px;text-align:center;transition:.2s}
.drop-zone:hover{background:#eaf9ee;border-color:#329b53}
.drop-zone strong{font-size:17px;color:#409957;max-width:100%;overflow-wrap:anywhere}
.drop-zone span{font-size:14px;color:#75818a}
.drop-zone small{font-size:12px;color:#8a9690}
.upload-symbol{margin-bottom:4px}
.upload-success{color:#36a45a}
.jd-body{display:flex;flex-direction:column;gap:22px}
.jd-body textarea{width:100%;min-height:270px;resize:vertical;border:1px solid #d5d9e2;border-radius:10px;padding:19px 20px;color:#20283a;font-size:15px;line-height:1.65;outline:none;background:#fff}
.jd-body textarea:focus{border-color:#6577ed;box-shadow:0 0 0 3px rgba(91,105,230,.12)}
.jd-body textarea::placeholder{color:#9aa2b1}
.jd-footer{display:flex;align-items:center;justify-content:space-between;gap:15px;color:#818998;font-size:13px}
.primary-button{display:inline-flex;align-items:center;justify-content:center;gap:10px;border:0;border-radius:9px;padding:14px 21px;color:white;background:linear-gradient(100deg,#3565e8,#8037df);font-size:14px;font-weight:600;box-shadow:0 6px 13px rgba(83,75,211,.2);transition:transform .15s,filter .15s}
.primary-button:hover:not(:disabled){filter:brightness(1.05);transform:translateY(-1px)}
.error-banner{max-width:100%;display:flex;align-items:center;gap:9px;margin:18px 0 0;padding:12px 15px;border:1px solid #fecaca;border-radius:9px;background:#fff1f2;color:#b42335;font-size:13px}
.privacy-note{display:flex;align-items:center;gap:7px;margin:22px 0 0;color:#7c8798;font-size:12px}
.interview-layout{max-width:900px;min-height:calc(100vh - 78px);margin:0 auto;display:flex;flex-direction:column}
.interview-brand{display:flex;align-items:center;gap:12px;font-size:18px;font-weight:700}
.interview-content{width:100%;max-width:720px;margin:70px auto 30px;text-align:center}
.eyebrow{display:inline-flex;align-items:center;gap:8px;color:#6673d9;font-size:11px;font-weight:700;letter-spacing:1.5px}
.live-dot{width:8px;height:8px;border-radius:50%;background:#36b66a;box-shadow:0 0 0 4px rgba(54,182,106,.12)}
.interview-content>h1,.completion-layout h1{font-size:clamp(32px,5vw,44px);letter-spacing:-1.5px;margin:14px 0 9px}
.interview-subtitle,.completion-copy{color:#788295;font-size:15px;line-height:1.6;margin:0 auto}
.question-card{margin:36px 0 28px;padding:29px 32px;border:1px solid #e1e6f0;border-radius:16px;background:#fff;box-shadow:0 9px 24px rgba(32,47,83,.07);text-align:left}
.question-label{display:flex;align-items:center;gap:8px;color:#6c70d9;font-size:11px;font-weight:700;letter-spacing:1px}
.question-card h2{font-size:clamp(21px,3vw,27px);line-height:1.5;letter-spacing:-.5px;margin:20px 0 0;font-weight:600;color:#202a3c}
.question-meta{display:flex;gap:8px;margin-top:22px}
.question-meta span{padding:6px 10px;border-radius:20px;background:#f2f4fa;color:#70798b;font-size:11px}
.question-loading{display:flex;align-items:center;gap:10px;margin-top:25px;color:#758096}
.voice-status{display:flex;flex-direction:column;align-items:center;gap:9px;margin:27px 0 23px}
.voice-orb{width:66px;height:66px;border-radius:50%;display:grid;place-items:center;background:#e9edff;color:#596ce3}
.voice-orb.speaking{background:#e9edff;color:#536be8;animation:pulse 1.5s infinite}
.voice-orb.recording{background:#ffebed;color:#e34c5c;animation:pulse 1.2s infinite}
.voice-orb.processing,.voice-orb.loading{background:#e9edff;color:#596ce3}
.voice-orb.saved{background:#e6f8ed;color:#269653}
.voice-status strong{font-size:16px}
.voice-status>span{font-size:13px;color:#8490a1}
.record-button{display:inline-flex;align-items:center;justify-content:center;gap:10px;min-width:220px;border:0;border-radius:10px;padding:15px 24px;background:linear-gradient(100deg,#3867e9,#773bdd);color:#fff;font-size:14px;font-weight:600;box-shadow:0 7px 16px rgba(79,82,212,.2)}
.record-button:disabled{opacity:.45;cursor:not-allowed}
.stop-button{background:#dc4655;box-shadow:0 7px 16px rgba(220,70,85,.17)}
.next-button{min-width:220px}
.text-button{display:flex;align-items:center;gap:7px;margin:14px auto 0;border:0;background:transparent;color:#6470cf;font-size:13px}
.transcription-card{margin:25px auto 0;padding:17px 19px;max-width:650px;border:1px solid #d8eee0;border-radius:12px;background:#f4fbf6;text-align:left}
.transcription-card>div{display:flex;align-items:center;gap:8px;color:#32965a;font-size:13px}
.transcription-card p{margin:11px 0 0;color:#536174;font-size:14px;line-height:1.65}
.bottom-note{margin:auto auto 0;padding-top:25px;color:#98a1af;font-size:12px;text-align:center}
.completion-layout{max-width:570px;min-height:calc(100vh - 78px);margin:0 auto;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
.completion-icon{width:82px;height:82px;border-radius:50%;display:grid;place-items:center;background:#e6f8ed;color:#2eaa60;margin-bottom:25px}
.completion-layout h1{margin:13px 0 8px}
.completion-copy{max-width:440px}
.completion-card{display:flex;justify-content:space-around;gap:30px;width:100%;margin:32px 0 17px;padding:22px;border:1px solid #e3e7ef;border-radius:13px;background:#fff;box-shadow:0 7px 18px rgba(26,38,68,.05)}
.completion-stat{display:flex;flex-direction:column;gap:8px}
.completion-stat span{font-size:12px;color:#8a94a4}
.completion-stat strong{font-size:16px;color:#27334a}
.feedback-placeholder{display:flex;align-items:flex-start;gap:13px;width:100%;padding:17px;border:1px solid #e3e6ff;border-radius:12px;background:#f7f7ff;text-align:left;margin-bottom:24px;color:#6c69d9}
.feedback-placeholder strong{font-size:14px;color:#39415c}
.feedback-placeholder p{margin:5px 0 0;color:#7d8799;font-size:12px;line-height:1.5}
.spin{animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pulse{50%{box-shadow:0 0 0 9px rgba(90,105,220,.08)}}
@media(max-width:850px){.app-shell{padding:28px 22px}.setup-grid{grid-template-columns:1fr;gap:22px}.brand-header p{font-size:14px}.panel-heading{min-height:90px}.drop-zone,.jd-body textarea{min-height:220px}}
@media(max-width:520px){.app-shell{padding:22px 15px}.brand-mark{width:49px;height:49px;border-radius:12px}.brand-header{gap:12px}.brand-header h1{font-size:29px;letter-spacing:-1px}.brand-header p{font-size:12px;line-height:1.45}.feature-pills{gap:7px;margin:22px 0}.feature-pills span{font-size:11px;padding:8px 10px}.panel-heading{padding:18px}.panel-body{padding:18px}.jd-footer{align-items:stretch;flex-direction:column}.jd-footer .primary-button{width:100%}.question-card{padding:22px 20px;margin:25px 0}.interview-content{margin:55px auto 25px}.completion-card{gap:12px;padding:17px}.completion-stat strong{font-size:14px}}
`;

export default App;
