using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using HordeParty.Mobs;
using UnityEngine;

namespace HordeParty.Bench
{
    /// <summary>
    /// 3단계 기술 검증 진입점.
    /// - 임시 메시/VAT로 몹 4종(슬라임·질주꾼·돌격병·군주)을 구성
    /// - 목표 수만큼 계속 생성, 원본처럼 FPS 기반 자동 밀도 조절(선택)
    /// - HUD(F1로 숨김): FPS, 1% low, CPU/GPU ms, 시뮬레이션 ms
    /// - 자동 벤치마크: 단계별 측정 후 CSV 저장. 실행 인자 -hpbench 면 측정 후 종료, -noshadows 면 몹 그림자 끔
    /// 입력은 IMGUI 이벤트만 써서 Input System 설정과 무관하게 동작한다.
    /// </summary>
    [DefaultExecutionOrder(-50)]
    public class MobBenchmark : MonoBehaviour
    {
        public MobSystem mobs;
        public BenchHeroes heroes;
        public Material mobMaterial;

        [Header("임시 메시 (에셋 없이 검증)")]
        [Range(6, 128)] public int radialSegments = 12;
        [Range(4, 128)] public int rings = 10;
        [Tooltip("HordeParty > VAT Baker로 구운 실제 모델. 지정하면 임시 메시 대신 사용")]
        public VatClipSet overrideVat;

        [Header("생성")]
        public int targetCount = 10000;
        public int spawnPerFrame = 1500;

        [Header("자동 밀도 조절 (원본 방식)")]
        public bool autoAdjust;
        public float autoTargetFps = 60f;

        [Header("벤치마크")]
        public int[] benchmarkSteps = { 1000, 5000, 10000, 12000, 15000, 20000 };
        public float settleSeconds = 3f;
        public float sampleSeconds = 6f;

        readonly float[] frameMs = new float[600];
        int frameIdx, frameFilled;
        readonly FrameTiming[] timings = new FrameTiming[1];
        double cpuMs, gpuMs;
        float simMs, fpsAvg, fpsLow, statTimer, autoTimer;
        int vertsPerMob;

        bool showHud = true, running, sampling;
        string status = "", lastReport;
        readonly List<float> sampleFrames = new List<float>();
        double sampleCpu, sampleGpu, sampleSim, sampleAlive;
        int sampleCount;
        readonly List<string> resultLines = new List<string>();

        static readonly int[] Presets = { 1000, 5000, 10000, 12000, 20000 };

        void Awake()
        {
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = -1;

            Mesh mesh = null;
            VatClipSet vat = overrideVat;
            if (vat == null)
            {
                mesh = ProceduralMobFactory.CreateBlobMesh(radialSegments, rings);
                vat = ProceduralMobFactory.CreateTestVat(mesh);
            }
            if (vat != null && vat.mesh != null) mesh = vat.mesh;
            vertsPerMob = mesh != null ? mesh.vertexCount : 0;

            mobs.kinds = new[]
            {
                Kind("Slime",   mesh, vat, new Color(0.35f, 0.75f, 0.30f), 2.2f, 10f,  0.40f, 0.85f, 50f),
                Kind("Runner",  mesh, vat, new Color(0.85f, 0.35f, 0.25f), 4.6f, 6f,   0.30f, 0.70f, 25f),
                Kind("Charger", mesh, vat, new Color(0.55f, 0.55f, 0.60f), 3.0f, 30f,  0.50f, 1.15f, 20f),
                Kind("Lord",    mesh, vat, new Color(0.55f, 0.25f, 0.75f), 1.6f, 600f, 1.20f, 2.6f,  0.15f),
            };

            if (HasArg("-noshadows")) mobs.castShadows = false;
        }

        MobSystem.KindConfig Kind(string kindName, Mesh mesh, VatClipSet vat, Color tint,
            float speed, float hp, float radius, float scale, float weight)
        {
            return new MobSystem.KindConfig
            {
                name = kindName,
                mesh = mesh,
                material = mobMaterial,
                vat = vat,
                tint = tint,
                speed = speed,
                hp = hp,
                radius = radius,
                scale = scale,
                spawnWeight = weight,
            };
        }

        void Start()
        {
            if (HasArg("-hpbench")) StartCoroutine(RunBenchmark(true));
        }

        void Update()
        {
            float dtMs = Time.unscaledDeltaTime * 1000f;
            frameMs[frameIdx] = dtMs;
            frameIdx = (frameIdx + 1) % frameMs.Length;
            frameFilled = Mathf.Min(frameFilled + 1, frameMs.Length);

            FrameTimingManager.CaptureFrameTimings();
            if (FrameTimingManager.GetLatestTimings(1, timings) > 0)
            {
                cpuMs = Lerp(cpuMs, timings[0].cpuFrameTime, 0.1);
                gpuMs = Lerp(gpuMs, timings[0].gpuFrameTime, 0.1);
            }
            simMs = Mathf.Lerp(simMs, mobs.LastSimMs, 0.1f);

            statTimer += Time.unscaledDeltaTime;
            if (statTimer >= 0.5f)
            {
                statTimer = 0f;
                ComputeFps(Mathf.Min(frameFilled, 240), out fpsAvg, out fpsLow);
            }

            if (sampling)
            {
                sampleFrames.Add(dtMs);
                sampleCpu += timings[0].cpuFrameTime;
                sampleGpu += timings[0].gpuFrameTime;
                sampleSim += mobs.LastSimMs;
                sampleAlive += mobs.Count;
                sampleCount++;
            }

            // 생성 / 정리
            if (mobs.Ready)
            {
                int count = mobs.Count;
                if (count < targetCount)
                    mobs.Spawn(Mathf.Min(spawnPerFrame, targetCount - count), mobs.worldHalfSize * 0.55f, mobs.worldHalfSize * 0.95f);
                else if (count > targetCount + 200)
                    mobs.TrimTo(targetCount);
            }

            // 원본처럼 FPS에 따라 몹 밀도 자동 조절
            if (autoAdjust && !running)
            {
                autoTimer += Time.unscaledDeltaTime;
                if (autoTimer >= 0.5f)
                {
                    autoTimer = 0f;
                    if (fpsAvg < autoTargetFps * 0.92f) targetCount = Mathf.Max(500, (int)(targetCount * 0.93f));
                    else if (fpsAvg > autoTargetFps * 1.10f) targetCount = Mathf.Min(mobs.Capacity, (int)(targetCount * 1.05f) + 100);
                }
            }
        }

        void ComputeFps(int n, out float avg, out float low)
        {
            avg = low = 0f;
            if (n <= 0) return;
            var tmp = new float[n];
            for (int i = 0; i < n; i++)
                tmp[i] = frameMs[(frameIdx - 1 - i + frameMs.Length) % frameMs.Length];
            Array.Sort(tmp);
            avg = 1000f / Average(tmp, 0, n);
            int worst = Mathf.Max(1, n / 100);
            low = 1000f / Average(tmp, n - worst, worst);
        }

        static float Average(IList<float> a, int start, int len)
        {
            double s = 0;
            for (int i = start; i < start + len; i++) s += a[i];
            return (float)(s / Mathf.Max(1, len));
        }

        static double Lerp(double a, double b, double t) => a + (b - a) * t;

        IEnumerator RunBenchmark(bool quitAfter)
        {
            running = true;
            bool prevAuto = autoAdjust;
            autoAdjust = false;
            resultLines.Clear();

            var sb = new StringBuilder();
            sb.AppendLine("target,alive_avg,fps_avg,fps_1pct_low,frame_ms_avg,cpu_ms,gpu_ms,sim_ms,verts_per_mob,mob_shadows,resolution");

            while (!mobs.Ready) yield return null;

            foreach (int step in benchmarkSteps)
            {
                if (step > mobs.Capacity) continue;
                targetCount = step;

                status = $"{step:N0}: 안정화 중";
                float t = 0f;
                while (t < settleSeconds || (mobs.Count < step * 0.9f && t < settleSeconds + 10f))
                {
                    t += Time.unscaledDeltaTime;
                    yield return null;
                }

                status = $"{step:N0}: 측정 중";
                sampleFrames.Clear();
                sampleCpu = sampleGpu = sampleSim = sampleAlive = 0;
                sampleCount = 0;
                sampling = true;
                t = 0f;
                while (t < sampleSeconds)
                {
                    t += Time.unscaledDeltaTime;
                    yield return null;
                }
                sampling = false;

                int n = sampleFrames.Count;
                if (n == 0) continue;
                sampleFrames.Sort();
                float avgMs = Average(sampleFrames, 0, n);
                int worst = Mathf.Max(1, n / 100);
                float worstMs = Average(sampleFrames, n - worst, worst);
                int c = Mathf.Max(1, sampleCount);

                string line = string.Format(CultureInfo.InvariantCulture,
                    "{0},{1:F0},{2:F1},{3:F1},{4:F2},{5:F2},{6:F2},{7:F2},{8},{9},{10}x{11}",
                    step, sampleAlive / c, 1000f / avgMs, 1000f / worstMs, avgMs,
                    sampleCpu / c, sampleGpu / c, sampleSim / c,
                    vertsPerMob, mobs.castShadows ? 1 : 0, Screen.width, Screen.height);
                sb.AppendLine(line);
                resultLines.Add(line);
            }

            string path = Path.Combine(Application.persistentDataPath,
                $"mob_benchmark_{DateTime.Now:yyyyMMdd_HHmmss}.csv");
            File.WriteAllText(path, sb.ToString());
            lastReport = path;
            Debug.Log($"[MobBenchmark] 저장: {path}\n{sb}");
            status = "완료";

            autoAdjust = prevAuto;
            running = false;
            if (quitAfter)
            {
                yield return null;
                Application.Quit();
            }
        }

        static bool HasArg(string arg)
        {
            foreach (string a in Environment.GetCommandLineArgs())
                if (string.Equals(a, arg, StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }

        void OnGUI()
        {
            Event e = Event.current;
            if (e.type == EventType.KeyDown && e.keyCode == KeyCode.F1)
            {
                showHud = !showHud;
                e.Use();
            }
            if (!showHud || mobs == null) return;

            GUILayout.BeginArea(new Rect(10, 10, 420, Screen.height - 20), GUI.skin.box);
            GUILayout.Label($"FPS {fpsAvg:F0}   1% low {fpsLow:F0}");
            string gpu = gpuMs > 0.0001 ? gpuMs.ToString("F2") : "n/a";
            GUILayout.Label($"CPU {cpuMs:F2} ms   GPU {gpu} ms   Sim {simMs:F2} ms");
            GUILayout.Label($"Mobs {mobs.Count:N0} / target {targetCount:N0}   (cap {mobs.Capacity:N0})");

            var kc = new StringBuilder();
            for (int k = 0; k < mobs.kinds.Length && k < mobs.KindCounts.Length; k++)
                kc.Append(mobs.kinds[k].name).Append(' ').Append(mobs.KindCounts[k].ToString("N0")).Append("  ");
            GUILayout.Label(kc.ToString());
            GUILayout.Label($"Kills {mobs.KilledTotal:N0}   Verts/mob {vertsPerMob:N0}   Total verts {(long)vertsPerMob * mobs.Count:N0}");

            GUI.enabled = !running;
            GUILayout.BeginHorizontal();
            foreach (int p in Presets)
                if (GUILayout.Button(p >= 1000 ? $"{p / 1000}k" : p.ToString())) targetCount = p;
            if (GUILayout.Button("-1k")) targetCount = Mathf.Max(0, targetCount - 1000);
            if (GUILayout.Button("+1k")) targetCount = Mathf.Min(mobs.Capacity, targetCount + 1000);
            GUILayout.EndHorizontal();

            mobs.castShadows = GUILayout.Toggle(mobs.castShadows, "Mob shadows");
            if (heroes != null) heroes.attack = GUILayout.Toggle(heroes.attack, "Heroes attack (death/respawn churn)");
            autoAdjust = GUILayout.Toggle(autoAdjust, $"Auto density (target {autoTargetFps:F0} fps)");
            if (GUILayout.Button("Run benchmark → CSV")) StartCoroutine(RunBenchmark(false));
            GUI.enabled = true;

            if (!string.IsNullOrEmpty(status)) GUILayout.Label(status);
            foreach (string line in resultLines) GUILayout.Label(line);
            if (!string.IsNullOrEmpty(lastReport)) GUILayout.Label(lastReport);
            GUILayout.Label("F1: hide HUD");
            GUILayout.EndArea();
        }
    }
}
