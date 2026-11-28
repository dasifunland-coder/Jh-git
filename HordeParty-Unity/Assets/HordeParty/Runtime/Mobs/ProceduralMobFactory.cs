using UnityEngine;
using UnityEngine.Rendering;

namespace HordeParty.Mobs
{
    /// <summary>
    /// 에셋 없이 기술 검증을 돌리기 위한 임시 몹 메시와 VAT.
    /// 실제 모델은 에디터의 HordeParty > VAT Baker로 구운 VatClipSet을 쓴다.
    /// 클립 순서: 0 걷기, 1 공격, 2 사망.
    /// </summary>
    public static class ProceduralMobFactory
    {
        public const float Height = 1.2f;
        public const int MaxVatWidth = 16384;

        /// <summary>회전체 몸통 + 앞쪽(+Z) 주둥이. segments x rings로 버텍스 수(=GPU 부하)를 조절한다.</summary>
        public static Mesh CreateBlobMesh(int segments, int rings)
        {
            segments = Mathf.Clamp(segments, 6, 256);
            rings = Mathf.Clamp(rings, 4, 256);
            int cols = segments + 1;
            var verts = new Vector3[(rings + 1) * cols];
            var uvs = new Vector2[verts.Length];

            for (int r = 0; r <= rings; r++)
            {
                float t = r / (float)rings;
                float y = t * Height;
                float baseR = 0.42f * Mathf.Pow(Mathf.Sin(Mathf.PI * t), 0.55f) * (1f - 0.3f * t);
                for (int s = 0; s <= segments; s++)
                {
                    float a = s / (float)segments * Mathf.PI * 2f;
                    float rel = Mathf.DeltaAngle(0f, a * Mathf.Rad2Deg) * Mathf.Deg2Rad;
                    float snout = 0.45f * Mathf.Exp(-rel * rel / 0.18f) * Mathf.Exp(-(t - 0.68f) * (t - 0.68f) / 0.008f);
                    float rr = baseR * (1f + snout);
                    verts[r * cols + s] = new Vector3(Mathf.Sin(a) * rr, y, Mathf.Cos(a) * rr);
                    uvs[r * cols + s] = new Vector2(s / (float)segments, t);
                }
            }

            var tris = new int[rings * segments * 6];
            int k = 0;
            for (int r = 0; r < rings; r++)
            {
                for (int s = 0; s < segments; s++)
                {
                    int a = r * cols + s;
                    int b = a + cols;
                    tris[k++] = a; tris[k++] = a + 1; tris[k++] = b;
                    tris[k++] = a + 1; tris[k++] = b + 1; tris[k++] = b;
                }
            }

            var mesh = new Mesh { name = $"MobBlob_{verts.Length}v" };
            if (verts.Length > 65000) mesh.indexFormat = IndexFormat.UInt32;
            mesh.vertices = verts;
            mesh.uv = uvs;
            mesh.triangles = tris;
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }

        /// <summary>메시에 걷기/공격/사망 변형을 프레임마다 적용해 VAT를 만든다.</summary>
        public static VatClipSet CreateTestVat(Mesh mesh)
        {
            Vector3[] src = mesh.vertices;
            Vector3[] srcN = mesh.normals;
            int vc = src.Length;
            if (vc > MaxVatWidth)
            {
                Debug.LogError($"[VAT] 버텍스 {vc}개는 텍스처 가로 한계({MaxVatWidth})를 넘습니다.");
                return null;
            }

            var clips = new[]
            {
                new VatClipSet.Clip { name = "walk", frameCount = 16, fps = 16f, loop = true },
                new VatClipSet.Clip { name = "attack", frameCount = 12, fps = 14f, loop = true },
                new VatClipSet.Clip { name = "death", frameCount = 20, fps = 20f, loop = false },
            };
            int rows = 0;
            for (int i = 0; i < clips.Length; i++) { clips[i].startRow = rows; rows += clips[i].frameCount; }

            var pos = new Color[vc * rows];
            var nrm = new Color[vc * rows];
            for (int c = 0; c < clips.Length; c++)
            {
                int fc = clips[c].frameCount;
                for (int f = 0; f < fc; f++)
                {
                    float ph = clips[c].loop ? f / (float)fc : f / (float)(fc - 1);
                    int row = clips[c].startRow + f;
                    for (int v = 0; v < vc; v++)
                    {
                        Vector3 p = src[v];
                        Vector3 n = srcN[v];
                        Deform(c, ph, ref p, ref n);
                        pos[row * vc + v] = new Color(p.x, p.y, p.z, 1f);
                        nrm[row * vc + v] = new Color(n.x, n.y, n.z, 0f);
                    }
                }
            }

            var set = ScriptableObject.CreateInstance<VatClipSet>();
            set.name = "TestVAT";
            set.mesh = mesh;
            set.positions = MakeTexture("VAT_Pos", vc, rows, pos);
            set.normals = MakeTexture("VAT_Nrm", vc, rows, nrm);
            set.clips = clips;
            return set;
        }

        public static Texture2D MakeTexture(string name, int width, int height, Color[] data)
        {
            var tex = new Texture2D(width, height, TextureFormat.RGBAHalf, false, true)
            {
                name = name,
                filterMode = FilterMode.Point,
                wrapMode = TextureWrapMode.Clamp,
            };
            tex.SetPixels(data);
            tex.Apply(false, false);
            return tex;
        }

        static void Deform(int clip, float ph, ref Vector3 p, ref Vector3 n)
        {
            float h = Mathf.Clamp01(p.y / Height);
            switch (clip)
            {
                case 0: // 걷기: 통통 튀기 + 좌우 흔들림 + 앞으로 기울기
                {
                    float a = ph * Mathf.PI * 2f;
                    float bob = Mathf.Abs(Mathf.Sin(a)) * 0.07f;
                    float sy = 1f - 0.08f * Mathf.Cos(a * 2f);
                    float sxz = 1f / Mathf.Sqrt(sy);
                    p.x = p.x * sxz + Mathf.Sin(a) * 0.10f * h;
                    p.z = p.z * sxz + 0.10f * h;
                    p.y = p.y * sy + bob;
                    break;
                }
                case 1: // 공격: 뒤로 젖혔다가 앞으로 박기
                {
                    float s = ph < 0.35f ? -0.35f * (ph / 0.35f)
                            : ph < 0.55f ? Mathf.Lerp(-0.35f, 1f, (ph - 0.35f) / 0.2f)
                            : Mathf.Lerp(1f, 0f, (ph - 0.55f) / 0.45f);
                    p.z += s * 0.38f * h;
                    p.y *= 1f - 0.06f * Mathf.Max(0f, s);
                    break;
                }
                case 2: // 사망: 뒤로 쓰러지며 납작해짐
                {
                    float e = 1f - Mathf.Pow(1f - ph, 3f);
                    float ang = e * 1.45f;
                    float cs = Mathf.Cos(ang), sn = Mathf.Sin(ang);
                    float y = p.y, z = p.z;
                    p.z = z * cs - y * sn;
                    p.y = z * sn + y * cs;
                    p.y = Mathf.Max(p.y, 0f) * Mathf.Lerp(1f, 0.55f, e) + 0.02f;
                    float ny = n.y, nz = n.z;
                    n.z = nz * cs - ny * sn;
                    n.y = nz * sn + ny * cs;
                    break;
                }
            }
        }
    }
}
