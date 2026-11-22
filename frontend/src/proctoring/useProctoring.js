// useProctoring.js
// Camera + focus proctoring for the interview.
//
//  - Camera: runs COCO-SSD object detection on the webcam feed and flags a
//    second person or a digital device (phone, laptop, monitor/TV, remote).
//  - Focus: flags switching tabs / minimizing, and blocks the screen when
//    another application takes focus, asking the candidate to close it.
//  - Each category ("camera", "focus") allows MAX_WARNINGS - 1 warnings;
//    reaching MAX_WARNINGS calls onAutoSubmit(reason, log).
import { useCallback, useEffect, useRef, useState } from "react";

export const MAX_WARNINGS = 2;

const DETECT_INTERVAL_MS = 700;   // how often a frame is analysed
const CONSECUTIVE_HITS = 3;       // object must be seen in 3 frames in a row (~2 s)
const CAMERA_COOLDOWN_MS = 10000; // time to remove the object after a warning
const APP_AWAY_LIMIT_MS = 10000;  // another app may stay in front this long
const MIN_SCORE = 0.6;            // detector confidence needed to flag

// COCO-SSD class -> label shown to the candidate.
const DEVICE_CLASSES = {
  "cell phone": "Mobile phone",
  laptop: "Laptop",
  tv: "Monitor / TV screen",
  remote: "Handheld device"
};

export function useProctoring({ onAutoSubmit } = {}) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const modelRef = useRef(null);
  const intervalRef = useRef(null);
  const awayTimerRef = useRef(null);
  const activeRef = useRef(false);
  const countsRef = useRef({ camera: 0, focus: 0 });
  const hitsRef = useRef({});
  const cooldownUntilRef = useRef(0);
  const logRef = useRef([]);
  const onAutoSubmitRef = useRef(onAutoSubmit);
  onAutoSubmitRef.current = onAutoSubmit;

  const [status, setStatus] = useState("idle"); // idle | starting | active | error | stopped
  const [error, setError] = useState("");
  const [counts, setCounts] = useState({ camera: 0, focus: 0 });
  const [warning, setWarning] = useState(null);  // { type, message, count }
  const [blocker, setBlocker] = useState(null);  // "app" | "fullscreen" | "camera" | null
  const [detections, setDetections] = useState([]);
  const [log, setLog] = useState([]);

  /* ---------------------------------------------------------------- */
  /* Stop everything                                                   */
  /* ---------------------------------------------------------------- */
  const stop = useCallback(() => {
    activeRef.current = false;
    window.clearInterval(intervalRef.current);
    window.clearTimeout(awayTimerRef.current);
    streamRef.current?.getTracks().forEach((track) => {
      track.onended = null;
      track.stop();
    });
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    setBlocker(null);
    setWarning(null);
    setDetections([]);
    setStatus((s) => (s === "idle" ? s : "stopped"));
  }, []);

  /* ---------------------------------------------------------------- */
  /* Record a violation; auto-submit on the last allowed one           */
  /* ---------------------------------------------------------------- */
  const raise = useCallback(
    (type, message) => {
      if (!activeRef.current) return;

      const count = ++countsRef.current[type];
      const entry = { type, message, count, time: new Date().toLocaleTimeString() };
      logRef.current = [...logRef.current, entry];
      setCounts({ ...countsRef.current });
      setLog(logRef.current);

      if (count >= MAX_WARNINGS) {
        const reason = `${message} (warning ${count} of ${MAX_WARNINGS})`;
        stop();
        onAutoSubmitRef.current?.(reason, logRef.current);
      } else {
        setWarning(entry);
      }
    },
    [stop]
  );

  /* ---------------------------------------------------------------- */
  /* Camera                                                            */
  /* ---------------------------------------------------------------- */
  const attachCamera = useCallback(async () => {
    const raw = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
      // Ask for the microphone now too, so its permission prompt does not
      // appear (and steal focus) in the middle of the test.
      audio: true
    });
    raw.getAudioTracks().forEach((track) => track.stop());
    const stream = new MediaStream(raw.getVideoTracks());

    stream.getVideoTracks()[0].onended = () => {
      if (!activeRef.current) return;
      setBlocker("camera");
      raise("camera", "Camera was turned off or disconnected");
    };

    streamRef.current = stream;
    const video = videoRef.current;
    video.srcObject = stream;
    await video.play();
  }, [raise]);

  function drawBoxes(predictions) {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.lineWidth = 3;
    ctx.font = "16px Inter, sans-serif";

    for (const p of predictions) {
      const flagged = Boolean(DEVICE_CLASSES[p.class]);
      if (p.class !== "person" && !flagged) continue;
      const [x, y, w, h] = p.bbox;
      ctx.strokeStyle = flagged ? "#ef4444" : "#22c55e";
      ctx.strokeRect(x, y, w, h);
    }
  }

  const detectFrame = useCallback(async () => {
    const video = videoRef.current;
    const model = modelRef.current;
    if (!activeRef.current || !model || !video || video.readyState < 2) return;

    const predictions = (await model.detect(video, 10, 0.4)).filter(
      (p) => p.score >= MIN_SCORE
    );
    if (!activeRef.current) return;
    drawBoxes(predictions);

    const found = new Map(); // key -> message
    const people = predictions.filter((p) => p.class === "person").length;
    if (people > 1) found.set("people", `${people} people detected in the camera`);
    for (const p of predictions) {
      if (DEVICE_CLASSES[p.class]) found.set(p.class, `${DEVICE_CLASSES[p.class]} detected`);
    }
    setDetections([...found.values()]);

    // Only count objects seen in several consecutive frames, so one bad
    // frame does not cost the candidate a warning.
    const hits = {};
    for (const key of found.keys()) hits[key] = (hitsRef.current[key] || 0) + 1;
    hitsRef.current = hits;

    if (Date.now() < cooldownUntilRef.current) return;
    const confirmed = [...found.entries()].filter(([key]) => hits[key] >= CONSECUTIVE_HITS);
    if (confirmed.length) {
      hitsRef.current = {};
      cooldownUntilRef.current = Date.now() + CAMERA_COOLDOWN_MS;
      raise("camera", confirmed.map(([, msg]) => msg).join(", "));
    }
  }, [raise]);

  /* ---------------------------------------------------------------- */
  /* Start (call from a click handler)                                 */
  /* ---------------------------------------------------------------- */
  const start = useCallback(async () => {
    setError("");
    setStatus("starting");

    // Must run synchronously inside the click, before any await.
    const fullscreen = document.documentElement.requestFullscreen?.().catch(() => null);

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Camera access is not supported in this browser. Use the latest Chrome or Edge.");
      }
      await attachCamera();

      if (!modelRef.current) {
        // Loaded on demand so the main bundle stays small.
        const [tf, cocoSsd] = await Promise.all([
          import("@tensorflow/tfjs"),
          import("@tensorflow-models/coco-ssd")
        ]);
        await tf.ready();
        modelRef.current = await cocoSsd.load({ base: "lite_mobilenet_v2" });
      }

      countsRef.current = { camera: 0, focus: 0 };
      hitsRef.current = {};
      logRef.current = [];
      cooldownUntilRef.current = 0;
      setCounts({ camera: 0, focus: 0 });
      setLog([]);
      setWarning(null);

      await fullscreen;
      setBlocker(document.fullscreenElement ? null : "fullscreen");

      activeRef.current = true;
      setStatus("active");

      let busy = false;
      intervalRef.current = window.setInterval(async () => {
        if (busy) return;
        busy = true;
        try {
          await detectFrame();
        } catch (err) {
          console.warn("Proctoring detection failed for a frame:", err);
        } finally {
          busy = false;
        }
      }, DETECT_INTERVAL_MS);

      return true;
    } catch (err) {
      stop();
      setStatus("error");
      setError(
        err?.name === "NotAllowedError"
          ? "Camera and microphone permission is required for this test. Allow access and try again."
          : err?.name === "NotFoundError"
            ? "No camera or microphone was found."
            : err?.message || "Could not start proctoring."
      );
      return false;
    }
  }, [attachCamera, detectFrame, stop]);

  /* ---------------------------------------------------------------- */
  /* Tab switching, other applications, fullscreen                     */
  /* ---------------------------------------------------------------- */
  useEffect(() => {
    if (status !== "active") return undefined;

    const armAwayTimer = () => {
      window.clearTimeout(awayTimerRef.current);
      awayTimerRef.current = window.setTimeout(() => {
        if (!activeRef.current || document.hasFocus()) return;
        raise("focus", "Another application stayed open over the test");
        armAwayTimer(); // still away: the next period is the next warning
      }, APP_AWAY_LIMIT_MS);
    };

    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        window.clearTimeout(awayTimerRef.current);
        raise("focus", "You switched tabs or minimized the test window");
      }
    };

    const onBlur = () => {
      // A tab switch fires blur before visibilitychange; wait a moment and
      // treat it as "another application" only if the page is still visible.
      window.setTimeout(() => {
        if (!activeRef.current || document.visibilityState === "hidden" || document.hasFocus()) return;
        setBlocker("app");
        armAwayTimer();
      }, 300);
    };

    const onFocus = () => {
      window.clearTimeout(awayTimerRef.current);
      setBlocker((b) => (b === "app" ? (document.fullscreenElement ? null : "fullscreen") : b));
    };

    const onFullscreenChange = () => {
      if (!activeRef.current) return;
      setBlocker((b) =>
        document.fullscreenElement ? (b === "fullscreen" ? null : b) : b || "fullscreen"
      );
    };

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", onFocus);
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      window.clearTimeout(awayTimerRef.current);
    };
  }, [status, raise]);

  useEffect(() => stop, [stop]);

  /* ---------------------------------------------------------------- */
  /* Actions for the UI                                                */
  /* ---------------------------------------------------------------- */
  const returnToTest = useCallback(async () => {
    try {
      if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
    } catch {
      /* fullscreen refused; the blocker stays up */
    }
    if (document.fullscreenElement) setBlocker(null);
  }, []);

  const restartCamera = useCallback(async () => {
    try {
      await attachCamera();
      setBlocker(document.fullscreenElement ? null : "fullscreen");
    } catch {
      setError("Could not turn the camera back on. Check that no other app is using it.");
    }
  }, [attachCamera]);

  return {
    videoRef,
    canvasRef,
    status,
    error,
    counts,
    warning,
    blocker,
    detections,
    log,
    start,
    stop,
    dismissWarning: () => setWarning(null),
    returnToTest,
    restartCamera
  };
}
