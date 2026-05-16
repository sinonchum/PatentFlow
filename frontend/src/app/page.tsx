"use client";

import { useEffect, useState, useRef, type ReactNode } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { UploadCloud, FileText, Zap, Download, ChevronRight, Sparkles, Shield, BarChart3, Languages, FileEdit, X, Radio, Mic2, PhoneCall, Loader2 } from "lucide-react";

type TaskState = "PENDING" | "STARTED" | "PROGRESS" | "SUCCESS" | "FAILURE";

type ClaimChartRow = {
  feature_id?: string;
  claim_limitation?: string;
  disclosure?: string;
  assessment?: string;
  attorney_remarks?: string;
  prior_art_mapping?: string;
  evidence_source?: string;
  status?: string;
  d1_mapping?: string;
  // v2 fields from updated claim_chart.py
  limitation?: string;
  d1_disclosure?: string;
  remarks?: string;
};

type TaskResult = {
  status?: string;
  claim_chart?: ClaimChartRow[];
  cited_docs?: string[];
  translation_table_markdown?: string;
  translation_rows?: Array<{
    original_cn?: string;
    target_en?: string;
    back_cn?: string;
    has_risk?: boolean;
  }>;
  response_draft?: string;
};

type StatusResponse = {
  task_id: string;
  state: TaskState | string;
  meta?: { step?: string; percent?: number; substep_index?: number; substep_total?: number; [k: string]: unknown } | null;
  result?: TaskResult | null;
  error?: string | null;
};

type TranslationRow = {
  originalCn: string;
  targetEn: string;
  backCn: string;
  hasRisk: boolean;
};

function renderInlineMd(text: string) {
  const s = text || "";
  const parts: Array<{ bold: boolean; value: string }> = [];
  const re = /\*\*(.+?)\*\*/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s)) !== null) {
    if (m.index > last) {
      parts.push({ bold: false, value: s.slice(last, m.index) });
    }
    parts.push({ bold: true, value: m[1] || "" });
    last = re.lastIndex;
  }
  if (last < s.length) {
    parts.push({ bold: false, value: s.slice(last) });
  }

  const nodes: ReactNode[] = [];
  let key = 0;
  for (const p of parts) {
    const chunks = p.value.split("<br>");
    chunks.forEach((chunk, idx) => {
      if (p.bold) {
        nodes.push(
          <span
            key={`b-${key++}`}
            className="inline-flex items-center rounded bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 text-xs font-medium text-amber-200"
          >
            {chunk}
          </span>
        );
      }
      else nodes.push(chunk);
      if (idx < chunks.length - 1) nodes.push(<br key={`br-${key++}`} />);
    });
  }
  return nodes;
}

function claimStatusBadge(statusText: string | undefined) {
  const s = (statusText || "").toLowerCase().trim();
  if (!s) return { label: "—", className: "bg-white/[0.04] text-white/30 border-white/[0.06]" };
  // Strict exact-value matching first (assessment is always "Yes"/"No"/"Partial")
  if (s === "no")      return { label: "Distinguishing ✓", className: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25" };
  if (s === "partial") return { label: "Partial ⚠", className: "bg-amber-500/10 text-amber-200 border-amber-500/20" };
  if (s === "yes")     return { label: "Disclosed", className: "bg-white/[0.06] text-white/50 border-white/[0.08]" };
  // Fallback for unexpected longer strings
  if (s.startsWith("no") || s.includes("not disclosed")) return { label: "Distinguishing ✓", className: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25" };
  if (s.includes("partial"))  return { label: "Partial ⚠", className: "bg-amber-500/10 text-amber-200 border-amber-500/20" };
  if (s.startsWith("yes") || s.includes("fully disclosed")) return { label: "Disclosed", className: "bg-white/[0.06] text-white/50 border-white/[0.08]" };
  return { label: statusText || "—", className: "bg-white/[0.04] text-white/30 border-white/[0.06]" };
}

function parseMarkdownPipeTable3(md: string): TranslationRow[] {
  const text = (md || "").trim();
  if (!text) return [];

  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l);

  const rows: TranslationRow[] = [];
  for (const line of lines) {
    // Skip header / separator
    if (!line.startsWith("|")) continue;
    if (line.includes("---")) continue;
    if (line.includes("Original CN") || line.includes("原始中文")) continue;

    const cells = line
      .split("|")
      .map((c) => c.trim())
      .filter((c) => c.length > 0);
    if (cells.length < 3) continue;

    const originalCn = cells[0] || "";
    const targetEn = cells[1] || "";
    const backCn = cells[2] || "";
    const hasRisk = /CRITICAL:|VOCAB_ALERT|VERB_MISMATCH/i.test(originalCn) || /CRITICAL:|VOCAB_ALERT|VERB_MISMATCH/i.test(backCn);
    rows.push({ originalCn, targetEn, backCn, hasRisk });
  }
  return rows;
}

export default function Workspace() {
  const [showBanner, setShowBanner] = useState(true);
  const [isExecuting, setIsExecuting] = useState(false);

  const [examinerBias, setExaminerBias] = useState("Jukka Tapaninen - Telecom");
  const [claimType, setClaimType] = useState("Method");
  const [attorneyProfile, setAttorneyProfile] = useState<"Default" | "Sinon" | "Karine">("Default");
  const [usePrivacyMode, setUsePrivacyMode] = useState(false);
  const [showMemoryEditor, setShowMemoryEditor] = useState(false);
  const [memoryKind, setMemoryKind] = useState<"phrasing_rule" | "examiner_strategy">("phrasing_rule");
  const [memoryDraft, setMemoryDraft] = useState("");
  const [memorySaving, setMemorySaving] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memorySavedAt, setMemorySavedAt] = useState<string | null>(null);

  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskState, setTaskState] = useState<TaskState | string | null>(null);
  const [taskStep, setTaskStep] = useState<string>("");
  const [queuePosition, setQueuePosition] = useState<number | null>(null);
  const [queueSize, setQueueSize] = useState<number | null>(null);
  const [taskPercent, setTaskPercent] = useState<number>(0);
  const [taskSubstepIndex, setTaskSubstepIndex] = useState<number | null>(null);
  const [taskSubstepTotal, setTaskSubstepTotal] = useState<number | null>(null);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [result, setResult] = useState<TaskResult | null>(null);

  const [officeActionText, setOfficeActionText] = useState<string>("");
  const [specificationText, setSpecificationText] = useState<string>("");
  const [isUploadingOA, setIsUploadingOA] = useState(false);
  const [isUploadingSpec, setIsUploadingSpec] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const officeActionInputRef = useRef<HTMLInputElement>(null);
  const specificationInputRef = useRef<HTMLInputElement>(null);

  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
  const VOICE_SERVER = process.env.NEXT_PUBLIC_VOICE_SERVER_URL || "http://localhost:7860";
  const API_KEY = process.env.NEXT_PUBLIC_PATENTFLOW_API_KEY || "";
  const apiHeaders = (extra: Record<string, string> = {}) => (
    API_KEY ? { ...extra, "X-API-Key": API_KEY } : extra
  );

  const [voiceStarting, setVoiceStarting] = useState(false);
  const [voiceEnding, setVoiceEnding] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [voiceSessionId, setVoiceSessionId] = useState<string | null>(null);
  const [voiceStatus, setVoiceStatus] = useState<string>("");
  const voiceWsRef = useRef<WebSocket | null>(null);
  const voicePlayerRef = useRef<{ stop: () => void; handleMessage: (data: unknown) => void } | null>(null);
  const voiceStartSentRef = useRef(false);

  const voiceRuntimeWindow = () => window as typeof window & {
    SyncedAudioPlayer?: new (options: Record<string, unknown>) => { start: () => Promise<void>; stop: () => void; handleMessage: (data: unknown) => void };
    __pcmOutput?: boolean;
    __patentFlowVoiceScripts?: Promise<void>;
  };

  const loadVoiceScript = (src: string) => new Promise<void>((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load voice runtime: ${src}`));
    document.body.appendChild(script);
  });

  const ensureVoiceRuntime = async () => {
    const runtime = voiceRuntimeWindow();
    if (!runtime.__patentFlowVoiceScripts) {
      runtime.__patentFlowVoiceScripts = (async () => {
        await loadVoiceScript(`/voice-runtime/opus-encoder.js`);
        await loadVoiceScript(`/voice-runtime/audio-processor.js`);
        await loadVoiceScript(`/voice-runtime/synced-audio-player.js`);
        const audioConfigResp = await fetch(`${VOICE_SERVER.replace(/\/$/, "")}/api/audio-config`);
        const audioConfig = await audioConfigResp.json();
        runtime.__pcmOutput = Boolean(audioConfig?.pcm);
      })();
    }
    await runtime.__patentFlowVoiceScripts;
    if (!runtime.SyncedAudioPlayer) {
      throw new Error("Voice runtime loaded, but SyncedAudioPlayer is unavailable.");
    }
    return runtime;
  };

  const closeVoiceResources = () => {
    voiceStartSentRef.current = false;
    const ws = voiceWsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stop" }));
      ws.close();
    } else if (ws && ws.readyState === WebSocket.CONNECTING) {
      ws.close();
    }
    voiceWsRef.current = null;
    if (voicePlayerRef.current) {
      voicePlayerRef.current.stop();
      voicePlayerRef.current = null;
    }
  };

  const handleStartVoice = async () => {
    setVoiceStarting(true);
    setVoiceError(null);
    setVoiceStatus("Starting audio session");
    voiceStartSentRef.current = false;

    try {
      const activeClaimChart = (result?.claim_chart || []).slice(0, 12).map((row, idx) => ({
        id: row.feature_id || String(idx + 1),
        limitation: row.claim_limitation || row.limitation || "",
        disclosure: row.prior_art_mapping || row.d1_disclosure || row.disclosure || row.d1_mapping || "",
        assessment: row.status || row.assessment || "",
        remarks: row.attorney_remarks || row.remarks || "",
      }));

      const resp = await fetch(`${VOICE_SERVER}/start_bot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "patentflow-web",
          attorney_profile: attorneyProfile,
          attorney_name: resolvedAttorneyName,
          examiner_preference: examinerBias,
          claim_type: claimType,
          office_action_text: officeActionText.slice(0, 18000),
          specification_text: specificationText.slice(0, 18000),
          task_id: taskId,
          task_state: taskState,
          latest_result: result
            ? {
                status: result.status,
                cited_docs: result.cited_docs || [],
                claim_chart: activeClaimChart,
                translation_rows: (result.translation_rows || []).slice(0, 20),
                response_draft: (result.response_draft || "").slice(0, 8000),
              }
            : null,
        }),
      });

      const rawText = await resp.text();
      let data: Record<string, unknown> = {};
      if (rawText) {
        try {
          data = JSON.parse(rawText) as Record<string, unknown>;
        } catch {
          data = { message: rawText };
        }
      }

      if (!resp.ok) {
        throw new Error(
          typeof data.error === "string"
            ? data.error
            : typeof data.detail === "string"
              ? data.detail
              : `Voice server returned HTTP ${resp.status}`
        );
      }

      const sessionId = typeof data.session_id === "string" ? data.session_id : "";

      if (!sessionId) {
        throw new Error("Voice server responded without a session id.");
      }

      setVoiceStatus("Loading voice runtime");
      const runtime = await ensureVoiceRuntime();

      setVoiceStatus("Requesting microphone access");
      const voicesResp = await fetch(`${VOICE_SERVER}/api/voices`);
      const voicesData = await voicesResp.json();
      const firstVoice = Array.isArray(voicesData?.voices) ? voicesData.voices[0] : null;
      const voiceName = firstVoice?.name || "unknow";
      const voiceId = firstVoice?.voice_id || "";
      const voiceLang = firstVoice?.language || "en";

      const promptResp = await fetch(`${VOICE_SERVER}/context/${encodeURIComponent(sessionId)}`);
      const promptData = promptResp.ok ? await promptResp.json() : {};
      const patentflowPrompt = typeof promptData?.prompt === "string" ? promptData.prompt : undefined;

      const PlayerCtor = runtime.SyncedAudioPlayer;
      if (!PlayerCtor) {
        throw new Error("Voice runtime is unavailable.");
      }
      const player = new PlayerCtor({
        basePath: `/voice-runtime`,
        sampleRate: 24000,
        pcmOutput: runtime.__pcmOutput || false,
        echoCancellation: true,
        onEncodedAudio: (opusData: ArrayBuffer | Blob | Uint8Array) => {
          const currentWs = voiceWsRef.current;
          if (voiceStartSentRef.current && currentWs && currentWs.readyState === WebSocket.OPEN) {
            currentWs.send(opusData);
          }
        },
        onText: ({ text, isUser }: { text?: string; isUser?: boolean }) => {
          if (!text) return;
          setVoiceStatus(isUser ? "Listening" : "Assistant responding");
        },
        onEvent: (eventType: string) => {
          if (eventType === "demo_mode") setVoiceStatus("Voice demo mode");
        },
        onError: (error: Error) => {
          setVoiceError(error.message);
          setVoiceStatus("Voice error");
        },
      });
      voicePlayerRef.current = player;
      await player.start();

      const voiceServerUrl = new URL(VOICE_SERVER);
      const wsProtocol = voiceServerUrl.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${wsProtocol}//${voiceServerUrl.host}/ws/chat`);
      voiceWsRef.current = ws;

      await new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(() => reject(new Error("Voice websocket connection timed out.")), 15000);
        ws.onmessage = (event) => voicePlayerRef.current?.handleMessage(event.data);
        ws.onclose = () => {
          voiceWsRef.current = null;
          setVoiceStatus((current) => current === "Listening" ? "Voice disconnected" : current);
        };
        ws.onopen = () => {
          window.clearTimeout(timeout);
          ws.send(JSON.stringify({
            type: "start",
            voice_name: voiceName,
            voice_id: voiceId,
            language: voiceLang,
            prompt: patentflowPrompt,
          }));
          voiceStartSentRef.current = true;
          resolve();
        };
        ws.onerror = () => {
          window.clearTimeout(timeout);
          reject(new Error("Voice websocket connection error."));
        };
      });

      setVoiceSessionId(sessionId);
      setVoiceStatus("Listening");
    } catch (err) {
      closeVoiceResources();
      setVoiceSessionId(null);
      setVoiceStatus("Voice failed");
      const message = err instanceof Error ? err.message : String(err);
      setVoiceError(
        /permission denied|notallowederror|microphone/i.test(message)
          ? "Microphone permission is required to start the session. Allow microphone access for this page and try again."
          : message
      );
    } finally {
      setVoiceStarting(false);
    }
  };

  const handleEndVoice = async () => {
    if (!voiceSessionId) return;
    setVoiceEnding(true);
    setVoiceError(null);
    setVoiceStatus("Ending voice session");

    try {
      closeVoiceResources();
      await fetch(`${VOICE_SERVER}/end_session/${encodeURIComponent(voiceSessionId)}`, {
        method: "POST",
      });
      setVoiceSessionId(null);
      setVoiceStatus("");
    } catch (err) {
      setVoiceError(err instanceof Error ? err.message : String(err));
    } finally {
      setVoiceEnding(false);
    }
  };

  const uploadFile = async (file: File): Promise<string> => {
    const formData = new FormData();
    formData.append("file", file);
    const resp = await fetch(`${API_BASE}/api/upload`, {
      method: "POST",
      headers: apiHeaders(),
      body: formData,
    });
    const data = await resp.json();
    if (data.status !== "success") throw new Error(data.error || "Upload failed");
    return data.text as string;
  };

  const handleOfficeActionUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploadingOA(true);
    setUploadError(null);
    try {
      const text = await uploadFile(file);
      setOfficeActionText(text);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsUploadingOA(false);
    }
  };

  const handleSpecificationUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploadingSpec(true);
    setUploadError(null);
    try {
      const text = await uploadFile(file);
      setSpecificationText(text);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsUploadingSpec(false);
    }
  };

  const resolvedAttorneyName = attorneyProfile === "Default" ? "" : attorneyProfile;

  const handleSaveMemory = async () => {
    setMemoryError(null);
    setMemorySavedAt(null);

    if (!resolvedAttorneyName) {
      setMemoryError("Select an attorney profile first.");
      return;
    }

    const text = (memoryDraft || "").trim();
    if (!text) {
      setMemoryError("Enter a rule or strategy to remember.");
      return;
    }

    setMemorySaving(true);
    try {
      const resp = await fetch(`${API_BASE}/api/memory/${encodeURIComponent(resolvedAttorneyName)}`, {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(
          memoryKind === "phrasing_rule"
            ? { phrasing_rule: text }
            : { examiner_strategy: text }
        ),
      });

      if (!resp.ok) {
        const body = await resp.text();
        throw new Error(body || `HTTP ${resp.status}`);
      }

      setMemoryDraft("");
      setMemorySavedAt(new Date().toLocaleTimeString());
      setShowMemoryEditor(false);
    } catch (e) {
      setMemoryError(e instanceof Error ? e.message : String(e));
    } finally {
      setMemorySaving(false);
    }
  };

  const handleExecute = async () => {
    setIsExecuting(true);
    setTaskError(null);
    setResult(null);
    setTaskState("PENDING");
    setTaskStep("Queued");
    setQueuePosition(null);
    setQueueSize(null);
    setTaskPercent(0);
    setTaskSubstepIndex(0);
    setTaskSubstepTotal(5);

    try {
      const resp = await fetch(`${API_BASE}/api/generate`, {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          office_action_text: officeActionText,
          specification_text: specificationText,
          examiner_preference: examinerBias,
          claim_type: claimType,
          attorney_name: resolvedAttorneyName,
          use_privacy_mode: usePrivacyMode,
        }),
      });

      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `HTTP ${resp.status}`);
      }

      const data = (await resp.json()) as { task_id?: string; queue_position?: number | null; queue_size?: number | null };
      if (!data.task_id) {
        throw new Error("Missing task_id from /api/generate");
      }
      setTaskId(data.task_id);
      if (typeof data.queue_position === "number") {
        setQueuePosition(data.queue_position);
      }
      if (typeof data.queue_size === "number") {
        setQueueSize(data.queue_size);
      }
      setTaskStep("Queued");
    } catch (e) {
      setTaskError(e instanceof Error ? e.message : String(e));
      setIsExecuting(false);
      setTaskId(null);
      setTaskState("FAILURE");
    }
  };

  useEffect(() => {
    if (!taskId || !isExecuting) return;

    let cancelled = false;
    let timeoutId: number | null = null;
    let delayMs = 2000;
    const maxDelayMs = 10000;

    const poll = async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/status/${taskId}`, { headers: apiHeaders() });
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text || `HTTP ${resp.status}`);
        }
        const data = (await resp.json()) as StatusResponse;
        if (cancelled) return;

        setTaskState(data.state);
        const step = data?.meta?.step;
        if (typeof step === "string" && step) {
          setTaskStep(step);
        }

        const qp = data?.meta?.queue_position;
        if (typeof qp === "number") {
          setQueuePosition(qp);
        }

        const qs = data?.meta?.queue_size;
        if (typeof qs === "number") {
          setQueueSize(qs);
        }

        const percent = data?.meta?.percent;
        if (typeof percent === "number") {
          setTaskPercent(Math.max(0, Math.min(100, percent)));
        }

        const substepIndex = data?.meta?.substep_index;
        if (typeof substepIndex === "number") {
          setTaskSubstepIndex(substepIndex);
        }

        const substepTotal = data?.meta?.substep_total;
        if (typeof substepTotal === "number") {
          setTaskSubstepTotal(substepTotal);
        }

        if (data.state === "SUCCESS") {
          setResult(data.result || null);
          setIsExecuting(false);
          if (timeoutId !== null) {
            window.clearTimeout(timeoutId);
          }
          // Scroll to results section
          setTimeout(() => {
            const tabsSection = document.querySelector('section[class*="pb-16"]');
            if (tabsSection) {
              tabsSection.scrollIntoView({ behavior: "smooth", block: "start" });
            }
          }, 100);
          return;
        }

        if (data.state === "FAILURE") {
          setTaskError(data.error || "Task failed");
          setIsExecuting(false);
          if (timeoutId !== null) {
            window.clearTimeout(timeoutId);
          }
          return;
        }

        // Schedule next poll with exponential backoff.
        delayMs = Math.min(maxDelayMs, delayMs * 2);
        timeoutId = window.setTimeout(poll, delayMs);
      } catch (e) {
        if (cancelled) return;
        setTaskError(e instanceof Error ? e.message : String(e));
        setIsExecuting(false);
        if (timeoutId !== null) {
          window.clearTimeout(timeoutId);
        }
      }

      // First poll delay: 2s
    };

    timeoutId = window.setTimeout(poll, delayMs);

    return () => {
      cancelled = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [taskId, isExecuting, API_BASE]);

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white font-sans relative overflow-x-hidden">
      {/* Background gradient effects */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-[-20%] left-[-10%] w-[600px] h-[600px] bg-purple-600/10 rounded-full blur-[120px]" />
        <div className="absolute bottom-[-20%] right-[-10%] w-[500px] h-[500px] bg-blue-600/8 rounded-full blur-[100px]" />
        <div className="absolute top-[40%] right-[20%] w-[300px] h-[300px] bg-indigo-500/5 rounded-full blur-[80px]" />
      </div>

      {/* Demo Banner */}
      {showBanner && (
        <div className="relative z-20 w-full bg-gradient-to-r from-purple-950/80 via-indigo-950/80 to-blue-950/80 border-b border-purple-500/20 backdrop-blur-xl">
          <div className="max-w-7xl mx-auto px-6 py-2.5 flex items-center justify-center gap-3">
            <div className="flex items-center gap-2.5">
              <div className="relative flex items-center justify-center">
                <Radio className="w-3.5 h-3.5 text-purple-400" />
                <span className="absolute w-2 h-2 rounded-full bg-purple-400 animate-ping opacity-40" />
              </div>
              <span className="text-xs sm:text-sm font-medium text-white/90 tracking-wide">
                <span className="text-purple-300 font-semibold">Live UI Demo</span>
                <span className="mx-2 text-white/20">·</span>
                <span className="text-white/60">The core AI engine runs 100% locally for client confidentiality.</span>
              </span>
              <Shield className="w-3.5 h-3.5 text-emerald-400/70 hidden sm:block" />
            </div>
            <button
              onClick={() => setShowBanner(false)}
              className="absolute right-4 p-1 rounded-md hover:bg-white/10 text-white/30 hover:text-white/60 transition-colors"
              aria-label="Dismiss banner"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Top Nav */}
      <nav className="relative z-10 border-b border-white/[0.06] bg-black/20 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-blue-600 flex items-center justify-center">
              <Zap className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-semibold tracking-tight">PatentFlow</span>
            <span className="text-xs text-white/30 font-medium ml-1 hidden sm:inline">v2.0</span>
          </div>
          <div className="flex items-center gap-4">
            <div className="hidden md:flex items-center gap-2">
              <span className="text-xs text-zinc-400 tracking-wide">Attorney Profile:</span>
              <select
                value={attorneyProfile}
                onChange={(e) => {
                  const next = e.target.value as "Default" | "Sinon" | "Karine";
                  setAttorneyProfile(next);
                  setMemoryError(null);
                  setMemorySavedAt(null);
                }}
                className="h-8 bg-zinc-900 text-zinc-200 text-xs border border-zinc-800 rounded-sm px-2 focus:outline-none focus:ring-0"
              >
                <option value="Default">Default</option>
                <option value="Sinon">Sinon</option>
                <option value="Karine">Karine</option>
              </select>
            </div>
            <span className="text-xs text-white/40 font-medium hidden md:inline">Document Processing Workspace</span>
            <div className="h-4 w-px bg-white/10 hidden md:block" />
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-purple-500/10 border border-purple-500/20">
              <div className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" />
              <span className="text-xs text-purple-400 font-medium">Static Demo</span>
            </div>
          </div>
        </div>
      </nav>

      {/* Hero / Upload Section */}
      <section className="relative z-10 max-w-7xl mx-auto px-6 pt-12 pb-8">
        <div className="mb-10">
          <h1 className="text-3xl md:text-4xl font-bold tracking-tight mb-3">
            <span className="bg-gradient-to-r from-white via-white to-white/60 bg-clip-text text-transparent">
              Document Processing
            </span>
          </h1>
          <p className="text-white/40 text-sm max-w-xl leading-relaxed">
            Upload your EPO Office Action and Patent Specification to generate Art. 56 claim charts,
            translation verification tables, and response drafts.
          </p>
        </div>

        {/* Upload Cards + Config Row */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {/* Office Action Upload */}
          <div 
            className="group relative rounded-xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-sm p-5 hover:border-purple-500/30 hover:bg-white/[0.05] transition-all duration-300 cursor-pointer"
            onClick={() => officeActionInputRef.current?.click()}
          >
            <input
              type="file"
              ref={officeActionInputRef}
              onChange={handleOfficeActionUpload}
              accept=".txt,.pdf,.doc,.docx"
              className="hidden"
            />
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center flex-shrink-0 group-hover:bg-purple-500/20 transition-colors">
                <UploadCloud className="w-5 h-5 text-purple-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white/90 mb-1">Office Action</p>
                <p className="text-xs text-white/30">
                  {officeActionText ? "File loaded ✓" : "PDF or TXT format"}
                </p>
              </div>
            </div>
            <div className="mt-4 border border-dashed border-white/10 rounded-lg p-3 text-center hover:border-purple-500/30 transition-colors">
              <p className="text-xs text-white/25">
                {isUploadingOA ? "Extracting text…" : officeActionText ? officeActionText.slice(0, 50) + "…" : "Drop file or click to browse"}
              </p>
            </div>
          </div>

          {/* Patent Specification Upload */}
          <div 
            className="group relative rounded-xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-sm p-5 hover:border-blue-500/30 hover:bg-white/[0.05] transition-all duration-300 cursor-pointer"
            onClick={() => specificationInputRef.current?.click()}
          >
            <input
              type="file"
              ref={specificationInputRef}
              onChange={handleSpecificationUpload}
              accept=".txt,.pdf,.doc,.docx"
              className="hidden"
            />
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center flex-shrink-0 group-hover:bg-blue-500/20 transition-colors">
                <FileText className="w-5 h-5 text-blue-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white/90 mb-1">Patent Specification</p>
                <p className="text-xs text-white/30">
                  {specificationText ? "File loaded ✓" : "PDF, TXT, or DOCX"}
                </p>
              </div>
            </div>
            <div className="mt-4 border border-dashed border-white/10 rounded-lg p-3 text-center hover:border-blue-500/30 transition-colors">
              <p className="text-xs text-white/25">
                {isUploadingSpec ? "Extracting text…" : specificationText ? specificationText.slice(0, 50) + "…" : "Drop file or click to browse"}
              </p>
            </div>
          </div>

          {/* Configuration */}
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-sm p-5">
            <div className="space-y-4">
              <div>
                <Label className="text-xs font-medium text-white/40 uppercase tracking-wider mb-2 block">
                  Examiner Bias
                </Label>
                <Select value={examinerBias} onValueChange={setExaminerBias}>
                  <SelectTrigger className="w-full bg-white/[0.04] border-white/[0.08] text-white/80 text-sm h-9 rounded-lg hover:border-white/20 transition-colors">
                    <SelectValue placeholder="Select examiner" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1a1a2e] border-white/10">
                    <SelectItem value="Jukka Tapaninen - Telecom">Jukka Tapaninen — Telecom</SelectItem>
                    <SelectItem value="Maria Schmidt - Mechanics">Maria Schmidt — Mechanics</SelectItem>
                    <SelectItem value="Hans Mueller - Chemistry">Hans Mueller — Chemistry</SelectItem>
                    <SelectItem value="General - No Specific Bias">General — No Bias</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs font-medium text-white/40 uppercase tracking-wider mb-2 block">
                  Claim Type
                </Label>
                <Select value={claimType} onValueChange={setClaimType}>
                  <SelectTrigger className="w-full bg-white/[0.04] border-white/[0.08] text-white/80 text-sm h-9 rounded-lg hover:border-white/20 transition-colors">
                    <SelectValue placeholder="Select claim type" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1a1a2e] border-white/10">
                    <SelectItem value="Method">Method</SelectItem>
                    <SelectItem value="Apparatus">Apparatus</SelectItem>
                    <SelectItem value="System">System</SelectItem>
                    <SelectItem value="Product">Product</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <button
                  type="button"
                  onClick={() => setUsePrivacyMode((prev) => !prev)}
                  className="w-full flex items-center justify-between rounded-lg border px-3 py-2 text-xs transition-all duration-200 hover:border-white/20"
                  style={{
                    borderColor: usePrivacyMode ? "rgba(16,185,129,0.3)" : "rgba(255,255,255,0.08)",
                    background: usePrivacyMode ? "rgba(16,185,129,0.06)" : "rgba(255,255,255,0.02)",
                  }}
                >
                  <div className="flex items-center gap-2">
                    <Shield className={`w-3.5 h-3.5 ${usePrivacyMode ? "text-emerald-400" : "text-white/25"}`} />
                    <span className={`font-medium ${usePrivacyMode ? "text-emerald-100" : "text-white/30"}`}>
                      Privacy Mode (Local LLM)
                    </span>
                  </div>
                  <div
                    className={`w-8 h-4 rounded-full transition-colors duration-200 ${
                      usePrivacyMode ? "bg-emerald-500/60" : "bg-white/[0.08]"
                    }`}
                  >
                    <div
                      className={`w-3 h-3 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                        usePrivacyMode ? "translate-x-4" : "translate-x-0.5"
                      }`}
                      style={{ marginTop: "1px" }}
                    />
                  </div>
                </button>
                <p className="mt-1 text-[10px] text-white/20">
                  {usePrivacyMode ? "Fastino Pioneer route active" : "Online LLM routing active"}
                </p>
              </div>
            </div>
          </div>

          {/* Execute Button */}
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-sm p-5 flex flex-col justify-between">
            {uploadError && (
              <div className="mb-3 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-200/90">
                {uploadError}
              </div>
            )}
            <div className="mb-4">
              <p className="text-sm font-medium text-white/70 mb-1">Ready to process</p>
              <p className="text-xs text-white/30 leading-relaxed">
                Pipeline generates claim charts, translation tables, and response drafts.
              </p>
            </div>
            {isExecuting && (
              <div className="mb-3 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-white/50">Status</span>
                  <span className="text-xs text-white/70 font-medium">{taskState || "PENDING"}</span>
                </div>
                <div className="mt-1 text-xs text-white/40 truncate">
                  {queuePosition ? `Queued (Position ${queuePosition}${queueSize ? `/${queueSize}` : ""}) → ` : ""}
                  {taskStep || "Queued"}
                </div>
                <div className="mt-2 h-1.5 w-full rounded-full bg-white/[0.08] overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-purple-500 to-blue-500 transition-all duration-500"
                    style={{ width: `${taskPercent}%` }}
                  />
                </div>
                <div className="mt-1 text-[10px] text-white/35">
                  {taskSubstepIndex !== null && taskSubstepTotal !== null
                    ? `Step ${taskSubstepIndex}/${taskSubstepTotal}`
                    : "Step progress pending"}
                  <span className="ml-1">({taskPercent}%)</span>
                </div>
              </div>
            )}
            {taskError && (
              <div className="mb-3 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-200/90">
                {taskError}
              </div>
            )}
            <Button
              onClick={handleExecute}
              disabled={isExecuting}
              className="w-full bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 text-white border-0 rounded-lg h-10 font-medium text-sm shadow-lg shadow-purple-500/20 hover:shadow-purple-500/30 transition-all duration-300 group"
            >
              <Sparkles className={`w-4 h-4 mr-2 ${isExecuting ? 'animate-spin' : 'group-hover:animate-spin'}`} />
              {isExecuting ? 'Processing Document...' : 'Execute Pipeline'}
              {!isExecuting && <ChevronRight className="w-4 h-4 ml-1 opacity-60 group-hover:translate-x-0.5 transition-transform" />}
            </Button>
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-sm p-5">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center flex-shrink-0">
                <Mic2 className="w-5 h-5 text-emerald-300" />
              </div>
              <div>
                <p className="text-sm font-medium text-white/90 mb-1">Voice Assistant</p>
                <p className="text-xs text-white/35 leading-relaxed max-w-2xl">
                  Starts or ends a PatentFlow voice session. Voice server: {VOICE_SERVER}
                </p>
                {voiceSessionId && (
                  <p className="mt-2 inline-flex items-center rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100/90">
                    Session active{voiceStatus ? ` · ${voiceStatus}` : ""}
                  </p>
                )}
                {!voiceSessionId && voiceStatus && (
                  <p className="mt-2 inline-flex items-center rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-xs text-white/55">
                    {voiceStatus}
                  </p>
                )}
                {voiceError && (
                  <p className="mt-2 text-xs text-red-200/90 border border-red-500/20 bg-red-500/10 rounded-lg px-3 py-2">
                    {voiceError}
                  </p>
                )}
              </div>
            </div>
            {voiceSessionId ? (
              <Button
                onClick={handleEndVoice}
                disabled={voiceEnding}
                className="h-10 rounded-lg border border-red-500/25 bg-red-500/10 px-4 text-sm font-medium text-red-100 hover:bg-red-500/15 hover:border-red-500/40 transition-all"
              >
                {voiceEnding ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <X className="w-4 h-4 mr-2" />}
                {voiceEnding ? "Ending the session" : "End the session"}
              </Button>
            ) : (
              <Button
                onClick={handleStartVoice}
                disabled={voiceStarting}
                className="h-10 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-4 text-sm font-medium text-emerald-100 hover:bg-emerald-500/15 hover:border-emerald-500/40 transition-all"
              >
                {voiceStarting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <PhoneCall className="w-4 h-4 mr-2" />}
                {voiceStarting ? "Starting the session" : "Start the session"}
              </Button>
            )}
          </div>
        </div>
      </section>

      {/* Tabs Section */}
      <section className="relative z-10 max-w-7xl mx-auto px-6 pb-16">
        <Tabs defaultValue="claim-chart" className="w-full">
          <TabsList className="bg-transparent border-b border-white/[0.06] rounded-none p-0 h-auto justify-start space-x-1 mb-0">
            <TabsTrigger
              value="claim-chart"
              className="rounded-none rounded-t-lg border-b-2 border-transparent data-[state=active]:border-purple-500 data-[state=active]:text-white data-[state=active]:bg-white/[0.04] bg-transparent px-4 py-3 text-sm font-medium text-white/40 hover:text-white/70 transition-all gap-2"
            >
              <BarChart3 className="w-4 h-4" />
              Art. 56 Claim Chart
            </TabsTrigger>
            <TabsTrigger
              value="verifier"
              className="rounded-none rounded-t-lg border-b-2 border-transparent data-[state=active]:border-blue-500 data-[state=active]:text-white data-[state=active]:bg-white/[0.04] bg-transparent px-4 py-3 text-sm font-medium text-white/40 hover:text-white/70 transition-all gap-2"
            >
              <Languages className="w-4 h-4" />
              Art. 123(2) Verifier
            </TabsTrigger>
            <TabsTrigger
              value="draft"
              className="rounded-none rounded-t-lg border-b-2 border-transparent data-[state=active]:border-indigo-500 data-[state=active]:text-white data-[state=active]:bg-white/[0.04] bg-transparent px-4 py-3 text-sm font-medium text-white/40 hover:text-white/70 transition-all gap-2"
            >
              <FileEdit className="w-4 h-4" />
              Response Draft
            </TabsTrigger>
          </TabsList>

          {/* Tab 1: Claim Chart */}
          <TabsContent value="claim-chart" className="mt-0">
            <div className="rounded-b-xl rounded-tr-xl border border-white/[0.06] border-t-0 bg-white/[0.02] backdrop-blur-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                  <thead>
                    <tr className="border-b border-white/[0.06] bg-white/[0.02]">
                      <th className="px-5 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest w-14">ID</th>
                      <th className="px-5 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest">CLAIM LIMITATION</th>
                      <th className="px-5 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest">PRIOR ART DISCLOSURE</th>
                      <th className="px-5 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest w-36">ASSESSMENT</th>
                      <th className="px-5 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest">LLM REASONING</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(result?.claim_chart || []).length > 0 ? (
                      (result?.claim_chart || []).map((row, idx) => {
                        const limitation = row.claim_limitation || row.limitation || "";
                        const disclosure = row.prior_art_mapping || row.d1_disclosure || row.disclosure || row.d1_mapping || "";
                        const assessment = row.status || row.assessment || "";
                        const reasoning = row.attorney_remarks || row.remarks || "";
                        const badge = claimStatusBadge(assessment);
                        return (
                          <tr key={`${row.feature_id || idx}`} className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors group">
                            <td className="px-5 py-4 align-top font-mono text-sm text-purple-400/80 whitespace-nowrap">
                              {row.feature_id || String(idx + 1)}
                            </td>
                            <td className="px-5 py-4 align-top text-white/80 leading-relaxed max-w-sm">
                              <span className="text-xs whitespace-pre-wrap break-words">{limitation}</span>
                            </td>
                            <td className="px-5 py-4 align-top text-white/50 leading-relaxed max-w-sm">
                              <span className="text-xs line-clamp-5 break-words">{disclosure}</span>
                            </td>
                            <td className="px-5 py-4 align-top whitespace-nowrap">
                              <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${badge.className}`}>
                                {badge.label}
                              </span>
                            </td>
                            <td className="px-5 py-4 align-top text-white/35 text-xs leading-relaxed max-w-sm">
                              {reasoning ? (
                                <span className="italic line-clamp-6 break-words">{reasoning}</span>
                              ) : (
                                <span className="text-white/15">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })
                    ) : (
                      <tr>
                        <td colSpan={5} className="px-6 py-8 text-sm text-white/30">
                          {isExecuting ? "Generating claim chart…" : "No claim chart yet. Execute pipeline to generate results."}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {/* Summary bar */}
              <div className="border-t border-white/[0.06] bg-white/[0.02] px-6 py-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Shield className="w-4 h-4 text-emerald-400/80" />
                  <span className="text-xs text-white/50">
                    <span className="text-emerald-400 font-medium">{(result?.claim_chart || []).length} features</span>
                    {" "}mapped against {(result?.cited_docs || []).join(", ") || "prior art references"} — Art. 56 EPC · <span className="text-emerald-400/70">{(result?.claim_chart || []).filter(r => (r.status || r.assessment || "").toLowerCase() === "no").length} distinguishing</span>
                  </span>
                </div>
                <Button variant="ghost" className="text-xs text-white/30 hover:text-white/60 h-8 px-3 gap-1.5">
                  <Download className="w-3.5 h-3.5" />
                  Export
                </Button>
              </div>

              <div className="border-t border-zinc-800 bg-zinc-900/20 px-6 py-3">
                <div className="flex items-center justify-between gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      setShowMemoryEditor((v) => !v);
                      setMemoryError(null);
                      setMemorySavedAt(null);
                    }}
                    className="text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 px-2 py-1 rounded-sm transition-colors text-xs"
                  >
                    💾 Save edits to memory...
                  </button>

                  <div className="flex items-center gap-2">
                    {memorySavedAt && (
                      <span className="text-xs text-zinc-500">Saved {memorySavedAt}</span>
                    )}
                    {resolvedAttorneyName ? (
                      <span className="text-xs text-zinc-600">Profile: {resolvedAttorneyName}</span>
                    ) : (
                      <span className="text-xs text-zinc-600">Profile: Default</span>
                    )}
                  </div>
                </div>

                {showMemoryEditor && (
                  <div className="mt-3 grid grid-cols-1 md:grid-cols-[160px_1fr_auto] gap-2 items-start">
                    <select
                      value={memoryKind}
                      onChange={(e) => setMemoryKind(e.target.value as "phrasing_rule" | "examiner_strategy")}
                      className="h-8 bg-zinc-900 text-zinc-200 text-xs border border-zinc-800 rounded-sm px-2 focus:outline-none focus:ring-0"
                    >
                      <option value="phrasing_rule">Phrasing rule</option>
                      <option value="examiner_strategy">Examiner strategy</option>
                    </select>

                    <textarea
                      value={memoryDraft}
                      onChange={(e) => setMemoryDraft(e.target.value)}
                      placeholder="Rule to remember (e.g., Always use 'terminal device' instead of 'UE')..."
                      className="w-full min-h-[36px] h-9 bg-zinc-900 text-zinc-200 text-xs border border-zinc-800 rounded-sm px-2 py-2 leading-tight focus:outline-none focus:ring-0"
                    />

                    <button
                      type="button"
                      disabled={memorySaving}
                      onClick={handleSaveMemory}
                      className="h-8 px-3 text-xs rounded-sm border border-emerald-700/60 text-emerald-300/80 hover:text-emerald-200 hover:border-emerald-500/60 hover:bg-emerald-500/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {memorySaving ? "Saving" : "Save"}
                    </button>

                    {memoryError && (
                      <div className="md:col-span-3 text-xs text-amber-200/80 border border-amber-500/20 bg-amber-500/10 rounded-sm px-2 py-1">
                        {memoryError}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </TabsContent>

          <TabsContent value="verifier" className="mt-0">
            <div className="rounded-b-xl rounded-tr-xl border border-white/[0.06] border-t-0 bg-white/[0.02] backdrop-blur-sm overflow-hidden">
              <div className="overflow-x-auto">
                {(() => {
                  const apiRows = (result?.translation_rows || []).map((r) => ({
                    originalCn: r.original_cn || "",
                    targetEn: r.target_en || "",
                    backCn: r.back_cn || "",
                    hasRisk: Boolean(r.has_risk),
                  }));
                  const md = result?.translation_table_markdown || "";
                  const rows = apiRows.length ? apiRows : parseMarkdownPipeTable3(md);

                  if (!rows.length) {
                    return (
                      <div className="p-6 text-sm text-white/30">
                        {isExecuting ? "Generating translation verifier..." : "No verifier output yet."}
                      </div>
                    );
                  }

                  return (
                    <table className="w-full text-sm text-left">
                      <thead>
                        <tr className="border-b border-white/[0.06] bg-white/[0.02]">
                          <th className="px-6 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest w-1/3">Claim Segment / Original</th>
                          <th className="px-6 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest w-1/3">EPO Compliant Form / Target</th>
                          <th className="px-6 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest w-1/3">Art. 123(2) Risk / Verification</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r, idx) => (
                          <tr
                            key={idx}
                            className={`border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors ${r.hasRisk ? "bg-amber-500/5" : ""}`}
                          >
                            <td className="px-6 py-5 align-top text-white/60 leading-relaxed">{renderInlineMd(r.originalCn)}</td>
                            <td className="px-6 py-5 align-top text-white/80 leading-relaxed">{renderInlineMd(r.targetEn)}</td>
                            <td className={`px-6 py-5 align-top leading-relaxed text-xs ${r.hasRisk ? "text-amber-200" : "text-emerald-400/70"}`}>{renderInlineMd(r.backCn)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  );
                })()}
              </div>

              <div className="border-t border-zinc-800 bg-zinc-900/20 px-6 py-3">
                <div className="flex items-center justify-between gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      setShowMemoryEditor((v) => !v);
                      setMemoryError(null);
                      setMemorySavedAt(null);
                    }}
                    className="text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 px-2 py-1 rounded-sm transition-colors text-xs"
                  >
                    💾 Save edits to memory...
                  </button>

                  <div className="flex items-center gap-2">
                    {memorySavedAt && (
                      <span className="text-xs text-zinc-500">Saved {memorySavedAt}</span>
                    )}
                    {resolvedAttorneyName ? (
                      <span className="text-xs text-zinc-600">Profile: {resolvedAttorneyName}</span>
                    ) : (
                      <span className="text-xs text-zinc-600">Profile: Default</span>
                    )}
                  </div>
                </div>

                {showMemoryEditor && (
                  <div className="mt-3 grid grid-cols-1 md:grid-cols-[160px_1fr_auto] gap-2 items-start">
                    <select
                      value={memoryKind}
                      onChange={(e) => setMemoryKind(e.target.value as "phrasing_rule" | "examiner_strategy")}
                      className="h-8 bg-zinc-900 text-zinc-200 text-xs border border-zinc-800 rounded-sm px-2 focus:outline-none focus:ring-0"
                    >
                      <option value="phrasing_rule">Phrasing rule</option>
                      <option value="examiner_strategy">Examiner strategy</option>
                    </select>

                    <textarea
                      value={memoryDraft}
                      onChange={(e) => setMemoryDraft(e.target.value)}
                      placeholder="Rule to remember (e.g., Always use 'terminal device' instead of 'UE')..."
                      className="w-full min-h-[36px] h-9 bg-zinc-900 text-zinc-200 text-xs border border-zinc-800 rounded-sm px-2 py-2 leading-tight focus:outline-none focus:ring-0"
                    />

                    <button
                      type="button"
                      disabled={memorySaving}
                      onClick={handleSaveMemory}
                      className="h-8 px-3 text-xs rounded-sm border border-emerald-700/60 text-emerald-300/80 hover:text-emerald-200 hover:border-emerald-500/60 hover:bg-emerald-500/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {memorySaving ? "Saving" : "Save"}
                    </button>

                    {memoryError && (
                      <div className="md:col-span-3 text-xs text-amber-200/80 border border-amber-500/20 bg-amber-500/10 rounded-sm px-2 py-1">
                        {memoryError}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </TabsContent>

          {/* Tab 3: Response Draft */}
          <TabsContent value="draft" className="mt-0">
            <div className="rounded-b-xl rounded-tr-xl border border-white/[0.06] border-t-0 bg-white/[0.02] backdrop-blur-sm overflow-hidden">
              {/* Header bar */}
              <div className="px-6 py-4 border-b border-white/[0.06] flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-purple-400/60 mb-0.5">
                    Response to European Patent Office
                  </p>
                  <p className="text-sm font-medium text-white/70">
                    {result?.response_draft
                      ? "Generated from your uploaded case — edit inline below"
                      : isExecuting
                      ? "Drafting response from claim chart..."
                      : "Execute the pipeline to generate a case-specific response draft"}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button variant="ghost" className="text-xs text-white/30 hover:text-white/60 h-8 px-3 gap-1.5">
                    <Download className="w-3.5 h-3.5" />
                    Export TXT
                  </Button>
                </div>
              </div>

              {/* Editable draft body */}
              <div className="p-6">
                <textarea
                  value={result?.response_draft || (isExecuting ? "Generating response draft..." : "")}
                  onChange={(e) => setResult((prev) => ({ ...(prev || {}), response_draft: e.target.value }))}
                  placeholder={
                    "Execute the pipeline to generate a structured EPO response draft based on your uploaded Office Action and Patent Specification.\n\n" +
                    "The draft will include:\n" +
                    "  • Application number, examiner name, and OA date extracted from your Office Action\n" +
                    "  • Distinguishing features from the claim chart (Art. 56)\n" +
                    "  • Clarity objection stubs (Art. 84) if raised\n" +
                    "  • Request section\n\n" +
                    "You can edit the generated draft directly in this text area."
                  }
                  className="w-full min-h-[600px] bg-white/[0.03] border border-white/[0.08] rounded-lg p-5 text-xs text-white/80 leading-relaxed font-mono resize-y focus:outline-none focus:border-white/20"
                />
              </div>

              <div className="border-t border-white/[0.06] bg-white/[0.02] px-6 py-3 flex items-center justify-between">
                <span className="text-xs text-white/25">
                  {result?.response_draft
                    ? `${result.response_draft.split("\n").length} lines · editable`
                    : "No draft yet"}
                </span>
                <Button variant="ghost" className="text-xs text-white/30 hover:text-white/60 h-8 px-3 gap-1.5">
                  <Download className="w-3.5 h-3.5" />
                  Export TXT
                </Button>
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </section>

      {/* Footer */}
      <footer className="relative z-10 border-t border-white/[0.04] py-8">
        <div className="max-w-7xl mx-auto px-6 flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-white/20">
            <Zap className="w-3.5 h-3.5" />
            <span>PatentFlow — Offline-first · Secure · EPC Compliant</span>
          </div>
          <span className="text-xs text-white/15">© 2026</span>
        </div>
      </footer>
    </div>
  );
}
