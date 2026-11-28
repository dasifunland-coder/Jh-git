using System.Collections.Generic;
using System.IO;
using HordeParty.Bench;
using HordeParty.Mobs;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace HordeParty.EditorTools
{
    /// <summary>메뉴 HordeParty > ... 로 벤치마크 씬 생성과 Windows 빌드를 한 번에 한다.</summary>
    public static class BenchmarkSceneBuilder
    {
        const string Root = "Assets/HordeParty";
        const string ScenePath = Root + "/Scenes/MobBenchmark.unity";
        const string BuildPath = "Builds/MobBenchmark/HordePartyBench.exe";

        [MenuItem("HordeParty/Create Mob Benchmark Scene", priority = 1)]
        public static void CreateScene()
        {
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;

            Shader mobShader = Shader.Find("HordeParty/MobVAT");
            Shader litShader = Shader.Find("Universal Render Pipeline/Lit");
            if (mobShader == null || litShader == null)
            {
                EditorUtility.DisplayDialog("HordeParty",
                    "셰이더를 찾지 못했습니다. URP 프로젝트인지, MobVAT.shader에 컴파일 오류가 없는지 확인하세요.", "확인");
                return;
            }

            EditorPaths.EnsureFolder(Root + "/Materials");
            EditorPaths.EnsureFolder(Root + "/Scenes");

            Material mobMat = LoadOrCreateMaterial(Root + "/Materials/MobVAT.mat", mobShader);
            Material groundMat = LoadOrCreateMaterial(Root + "/Materials/Ground.mat", litShader);
            groundMat.SetColor("_BaseColor", new Color(0.20f, 0.17f, 0.15f));
            groundMat.SetFloat("_Smoothness", 0.15f);
            Material heroMat = LoadOrCreateMaterial(Root + "/Materials/HeroPlaceholder.mat", litShader);
            EditorUtility.SetDirty(groundMat);
            AssetDatabase.SaveAssets();

            Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            var lightGo = new GameObject("Directional Light");
            var light = lightGo.AddComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = 1.2f;
            light.color = new Color(1f, 0.94f, 0.85f);
            light.shadows = LightShadows.Soft;
            lightGo.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

            var camGo = new GameObject("Main Camera") { tag = "MainCamera" };
            var cam = camGo.AddComponent<Camera>();
            cam.fieldOfView = 50f;
            cam.nearClipPlane = 0.3f;
            cam.farClipPlane = 300f;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.05f, 0.05f, 0.07f);
            camGo.transform.position = new Vector3(0f, 42f, -38f);
            camGo.transform.LookAt(new Vector3(0f, 0f, 2f));

            GameObject ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
            ground.name = "Ground (160m)";
            ground.transform.localScale = new Vector3(16f, 1f, 16f);
            ground.GetComponent<Renderer>().sharedMaterial = groundMat;
            Object.DestroyImmediate(ground.GetComponent<Collider>());

            RenderSettings.fog = true;
            RenderSettings.fogMode = FogMode.Linear;
            RenderSettings.fogColor = new Color(0.05f, 0.05f, 0.07f);
            RenderSettings.fogStartDistance = 60f;
            RenderSettings.fogEndDistance = 140f;
            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = new Color(0.35f, 0.38f, 0.45f);
            RenderSettings.ambientEquatorColor = new Color(0.22f, 0.2f, 0.2f);
            RenderSettings.ambientGroundColor = new Color(0.08f, 0.07f, 0.06f);

            var mobs = new GameObject("MobSystem").AddComponent<MobSystem>();
            var heroes = new GameObject("BenchHeroes").AddComponent<BenchHeroes>();
            heroes.mobs = mobs;
            heroes.heroMaterial = heroMat;
            var bench = new GameObject("MobBenchmark").AddComponent<MobBenchmark>();
            bench.mobs = mobs;
            bench.heroes = heroes;
            bench.mobMaterial = mobMat;

            EditorSceneManager.SaveScene(scene, ScenePath);
            AddSceneToBuild(ScenePath);
            PlayerSettings.enableFrameTimingStats = true; // GPU ms 표시용

            Debug.Log($"[HordeParty] 벤치마크 씬 생성: {ScenePath}. Play를 누르세요. 정확한 수치는 빌드(HordeParty > Build Mob Benchmark)로 측정하세요.");
        }

        [MenuItem("HordeParty/Build Mob Benchmark (Windows)", priority = 2)]
        public static void BuildWindows()
        {
            if (!File.Exists(ScenePath)) CreateScene();
            PlayerSettings.enableFrameTimingStats = true;
            Directory.CreateDirectory(Path.GetDirectoryName(BuildPath));
            var options = new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = BuildPath,
                target = BuildTarget.StandaloneWindows64,
                options = BuildOptions.None,
            };
            BuildReport report = BuildPipeline.BuildPlayer(options);
            if (report.summary.result == BuildResult.Succeeded)
            {
                Debug.Log($"[HordeParty] 빌드 완료: {Path.GetFullPath(BuildPath)}  (자동 측정: HordePartyBench.exe -hpbench)");
                EditorUtility.RevealInFinder(BuildPath);
            }
            else
            {
                Debug.LogError($"[HordeParty] 빌드 실패: {report.summary.result}, 오류 {report.summary.totalErrors}개");
            }
        }

        static Material LoadOrCreateMaterial(string path, Shader shader)
        {
            var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (mat != null) return mat;
            mat = new Material(shader);
            AssetDatabase.CreateAsset(mat, path);
            return mat;
        }

        static void AddSceneToBuild(string path)
        {
            var scenes = new List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
            scenes.RemoveAll(s => s.path == path);
            scenes.Insert(0, new EditorBuildSettingsScene(path, true));
            EditorBuildSettings.scenes = scenes.ToArray();
        }
    }

    public static class EditorPaths
    {
        /// <summary>"Assets/A/B/C" 폴더를 AssetDatabase로 단계별 생성.</summary>
        public static void EnsureFolder(string path)
        {
            path = path.Replace('\\', '/').TrimEnd('/');
            if (AssetDatabase.IsValidFolder(path)) return;
            int slash = path.LastIndexOf('/');
            string parent = path.Substring(0, slash);
            EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, path.Substring(slash + 1));
        }
    }
}
