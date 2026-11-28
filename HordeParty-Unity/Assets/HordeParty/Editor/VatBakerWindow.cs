using System.Collections.Generic;
using HordeParty.Mobs;
using UnityEditor;
using UnityEngine;

namespace HordeParty.EditorTools
{
    /// <summary>
    /// 스킨드 메시 + 애니메이션 클립 → VAT(위치/노멀 RGBAHalf 텍스처) + 정적 메시 + VatClipSet.
    /// 2단계에서 KayKit 해골 등(glb, glTFast)을 임포트한 뒤 사용한다.
    /// 클립 순서가 곧 클립 번호: 0 걷기, 1 공격, 2 사망 (MobSystem.KindConfig 기본값).
    /// </summary>
    public class VatBakerWindow : EditorWindow
    {
        GameObject source;
        readonly List<AnimationClip> clips = new List<AnimationClip>();
        readonly List<bool> loops = new List<bool>();
        int fps = 30;
        string setName = "Skeleton";
        string outFolder = "Assets/HordeParty/VAT";
        Vector2 scroll;

        [MenuItem("HordeParty/VAT Baker", priority = 20)]
        static void Open() => GetWindow<VatBakerWindow>("VAT Baker");

        void OnGUI()
        {
            EditorGUILayout.HelpBox(
                "SkinnedMeshRenderer가 있는 모델(프리팹/glb)과 클립을 지정하세요.\n" +
                "클립 순서 = 클립 번호 (0 걷기, 1 공격, 2 사망). 버텍스는 16,384개 이하여야 합니다.\n" +
                "Humanoid 클립은 SampleAnimation이 제대로 동작하지 않을 수 있으니 Generic/Legacy로 임포트하세요.",
                MessageType.Info);

            source = (GameObject)EditorGUILayout.ObjectField("Model", source, typeof(GameObject), false);
            setName = EditorGUILayout.TextField("Name", setName);
            fps = EditorGUILayout.IntSlider("Bake FPS", fps, 10, 60);
            outFolder = EditorGUILayout.TextField("Output Folder", outFolder);

            if (source != null && GUILayout.Button("모델에 포함된 클립 불러오기")) FillClipsFromModel();

            EditorGUILayout.Space();
            scroll = EditorGUILayout.BeginScrollView(scroll, GUILayout.MaxHeight(260));
            for (int i = 0; i < clips.Count; i++)
            {
                EditorGUILayout.BeginHorizontal();
                clips[i] = (AnimationClip)EditorGUILayout.ObjectField($"[{i}]", clips[i], typeof(AnimationClip), false);
                loops[i] = EditorGUILayout.ToggleLeft("Loop", loops[i], GUILayout.Width(50));
                if (i > 0 && GUILayout.Button("↑", GUILayout.Width(22))) Swap(i, i - 1);
                if (GUILayout.Button("X", GUILayout.Width(22))) { clips.RemoveAt(i); loops.RemoveAt(i); break; }
                EditorGUILayout.EndHorizontal();
            }
            EditorGUILayout.EndScrollView();
            if (GUILayout.Button("+ 클립 칸 추가")) { clips.Add(null); loops.Add(true); }

            EditorGUILayout.Space();
            GUI.enabled = source != null && clips.Count > 0 && clips.TrueForAll(c => c != null);
            if (GUILayout.Button("Bake", GUILayout.Height(30))) Bake();
            GUI.enabled = true;
        }

        void Swap(int a, int b)
        {
            (clips[a], clips[b]) = (clips[b], clips[a]);
            (loops[a], loops[b]) = (loops[b], loops[a]);
        }

        void FillClipsFromModel()
        {
            clips.Clear();
            loops.Clear();
            foreach (Object o in AssetDatabase.LoadAllAssetsAtPath(AssetDatabase.GetAssetPath(source)))
            {
                if (o is AnimationClip c && !c.name.StartsWith("__preview__"))
                {
                    clips.Add(c);
                    string n = c.name.ToLowerInvariant();
                    loops.Add(!(n.Contains("death") || n.Contains("die") || n.Contains("dead")));
                }
            }
        }

        void Bake()
        {
            GameObject inst = Instantiate(source);
            inst.hideFlags = HideFlags.HideAndDontSave;
            inst.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            var baked = new Mesh();
            try
            {
                var smr = inst.GetComponentInChildren<SkinnedMeshRenderer>();
                if (smr == null) { Debug.LogError("[VAT] SkinnedMeshRenderer가 없습니다."); return; }

                var frames = new List<(Vector3[] p, Vector3[] n)>();
                var infos = new VatClipSet.Clip[clips.Count];
                int row = 0, vc = -1;
                Vector2[] uv = null;
                int[] tris = null;

                for (int ci = 0; ci < clips.Count; ci++)
                {
                    AnimationClip clip = clips[ci];
                    bool loop = loops[ci];
                    float len = Mathf.Max(clip.length, 1f / fps);
                    int fc = Mathf.Max(2, Mathf.CeilToInt(len * fps));
                    infos[ci] = new VatClipSet.Clip
                    {
                        name = clip.name,
                        startRow = row,
                        frameCount = fc,
                        fps = loop ? fc / len : (fc - 1) / len,
                        loop = loop,
                    };

                    for (int f = 0; f < fc; f++)
                    {
                        float t = loop ? f * len / fc : f * len / (fc - 1);
                        clip.SampleAnimation(inst, t);
                        smr.BakeMesh(baked);
                        Vector3[] v = baked.vertices;
                        Vector3[] n = baked.normals;
                        if (vc < 0)
                        {
                            vc = v.Length;
                            if (vc > ProceduralMobFactory.MaxVatWidth)
                            {
                                Debug.LogError($"[VAT] 버텍스 {vc}개 > {ProceduralMobFactory.MaxVatWidth}. 메시를 줄이세요.");
                                return;
                            }
                            uv = baked.uv;
                            tris = baked.triangles;
                        }
                        // BakeMesh 결과는 SMR 트랜스폼 기준(스케일 제외) → 모델 루트 기준으로 변환.
                        // 루트 모션은 inst.transform 역행렬로 상쇄되어 제자리 애니메이션이 된다.
                        Matrix4x4 toRoot = inst.transform.worldToLocalMatrix *
                                           Matrix4x4.TRS(smr.transform.position, smr.transform.rotation, Vector3.one);
                        for (int i = 0; i < vc; i++)
                        {
                            v[i] = toRoot.MultiplyPoint3x4(v[i]);
                            n[i] = toRoot.MultiplyVector(n[i]).normalized;
                        }
                        frames.Add((v, n));
                        row++;
                    }
                }

                var pos = new Color[vc * row];
                var nrm = new Color[vc * row];
                for (int r = 0; r < row; r++)
                {
                    for (int i = 0; i < vc; i++)
                    {
                        Vector3 p = frames[r].p[i], n = frames[r].n[i];
                        pos[r * vc + i] = new Color(p.x, p.y, p.z, 1f);
                        nrm[r * vc + i] = new Color(n.x, n.y, n.z, 0f);
                    }
                }

                var mesh = new Mesh { name = setName + "_VATMesh" };
                if (vc > 65000) mesh.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
                mesh.vertices = frames[0].p;
                mesh.normals = frames[0].n;
                if (uv != null && uv.Length == vc) mesh.uv = uv;
                mesh.triangles = tris;
                mesh.RecalculateBounds();

                Texture2D texPos = ProceduralMobFactory.MakeTexture(setName + "_VAT_Pos", vc, row, pos);
                Texture2D texNrm = ProceduralMobFactory.MakeTexture(setName + "_VAT_Nrm", vc, row, nrm);

                EditorPaths.EnsureFolder(outFolder);
                AssetDatabase.CreateAsset(mesh, $"{outFolder}/{setName}_VATMesh.asset");
                AssetDatabase.CreateAsset(texPos, $"{outFolder}/{setName}_VAT_Pos.asset");
                AssetDatabase.CreateAsset(texNrm, $"{outFolder}/{setName}_VAT_Nrm.asset");

                var set = CreateInstance<VatClipSet>();
                set.mesh = mesh;
                set.positions = texPos;
                set.normals = texNrm;
                set.clips = infos;
                AssetDatabase.CreateAsset(set, $"{outFolder}/{setName}_VAT.asset");
                AssetDatabase.SaveAssets();
                Selection.activeObject = set;
                Debug.Log($"[VAT] 완료: 버텍스 {vc}, 프레임 {row}, 클립 {infos.Length}개 → {outFolder}/{setName}_VAT.asset");
            }
            finally
            {
                DestroyImmediate(inst);
                DestroyImmediate(baked);
            }
        }
    }
}
