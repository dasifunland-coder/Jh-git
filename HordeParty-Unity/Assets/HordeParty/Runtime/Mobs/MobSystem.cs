using System.Collections.Generic;
using Unity.Collections;
using Unity.Jobs;
using Unity.Mathematics;
using UnityEngine;
using UnityEngine.Rendering;

namespace HordeParty.Mobs
{
    /// <summary>
    /// 몹 대량 처리 (Godot mob_system.gd 대응).
    /// - 시뮬레이션: NativeArray + Burst 잡 (격자 구축 → 추적/밀어내기 → 피해 → 압축)
    /// - 렌더링: 종류별 Graphics.RenderMeshPrimitives 1회 + StructuredBuffer 인스턴스 데이터 + VAT 셰이더
    /// 매 프레임 순서: 다른 스크립트가 Spawn/AddHit/SetHeroes → Update(시뮬) → LateUpdate(그리기)
    /// </summary>
    [DefaultExecutionOrder(100)]
    public class MobSystem : MonoBehaviour
    {
        [System.Serializable]
        public class KindConfig
        {
            public string name = "Slime";
            public Mesh mesh;
            public Material material;
            public VatClipSet vat;
            public Color tint = Color.white;
            public float speed = 2.5f;
            public float hp = 10f;
            public float radius = 0.4f;
            public float scale = 1f;
            public float spawnWeight = 1f;
            public int walkClip = 0;
            public int attackClip = 1;
            public int deathClip = 2;

            [System.NonSerialized] public Material runtimeMaterial;
            [System.NonSerialized] public MaterialPropertyBlock props;
            [System.NonSerialized] public Mesh drawMesh;
        }

        public KindConfig[] kinds = new KindConfig[0];
        [Tooltip("원본 MAX_MOBS는 12,000. 벤치마크용으로 여유 있게.")]
        public int capacity = 30000;
        public float worldHalfSize = 80f;
        public float cellSize = 1f;
        public float attackRange = 0.6f;
        public float deathDuration = 1.6f;
        public float acceleration = 8f;
        [Range(0f, 1f)] public float separation = 0.35f;
        public int maxNeighborChecks = 24;
        public bool castShadows = true;

        public const int MaxHeroes = 16;
        public const int MaxHitsPerFrame = 256;

        NativeArray<MobSim> mobsA, mobsB;
        NativeArray<MobGpu> gpuData;
        NativeArray<int> cellStart, cellCursor, mobCell, sorted;
        NativeArray<float3> heroes;
        NativeArray<HitEvent> hits;
        NativeArray<MobKindParams> kindParams;
        NativeArray<int> kindOffsets, kindCursor, result;
        GraphicsBuffer instanceBuffer;
        GridInfo grid;

        int count, gpuCount, heroCount;
        float totalWeight;
        bool ready;
        readonly List<HitEvent> pendingHits = new List<HitEvent>();
        Unity.Mathematics.Random rng;
        readonly System.Diagnostics.Stopwatch stopwatch = new System.Diagnostics.Stopwatch();

        static readonly int MobsId = Shader.PropertyToID("_Mobs");
        static readonly int OffsetId = Shader.PropertyToID("_InstanceOffset");
        static readonly int BaseColorId = Shader.PropertyToID("_BaseColor");
        static readonly int VatPosId = Shader.PropertyToID("_VatPos");
        static readonly int VatNrmId = Shader.PropertyToID("_VatNrm");
        static readonly int VatClipsId = Shader.PropertyToID("_VatClips");
        static readonly int UseVatId = Shader.PropertyToID("_UseVat");

        public int Count => count;
        public int Capacity => capacity;
        public bool Ready => ready;
        public float LastSimMs { get; private set; }
        public long KilledTotal { get; private set; }
        public int[] KindCounts { get; private set; } = new int[0];

        void Start() => Allocate();

        void Allocate()
        {
            if (kinds == null || kinds.Length == 0)
            {
                Debug.LogError("[MobSystem] kinds가 비어 있습니다.");
                return;
            }

            grid = new GridInfo
            {
                half = worldHalfSize,
                invCell = 1f / cellSize,
                dim = math.max(1, (int)math.ceil(worldHalfSize * 2f / cellSize)),
            };
            int cells = grid.dim * grid.dim;

            mobsA = new NativeArray<MobSim>(capacity, Allocator.Persistent);
            mobsB = new NativeArray<MobSim>(capacity, Allocator.Persistent);
            gpuData = new NativeArray<MobGpu>(capacity, Allocator.Persistent);
            cellStart = new NativeArray<int>(cells + 1, Allocator.Persistent);
            cellCursor = new NativeArray<int>(cells, Allocator.Persistent);
            mobCell = new NativeArray<int>(capacity, Allocator.Persistent);
            sorted = new NativeArray<int>(capacity, Allocator.Persistent);
            heroes = new NativeArray<float3>(MaxHeroes, Allocator.Persistent);
            hits = new NativeArray<HitEvent>(MaxHitsPerFrame, Allocator.Persistent);
            kindParams = new NativeArray<MobKindParams>(kinds.Length, Allocator.Persistent);
            kindOffsets = new NativeArray<int>(kinds.Length + 1, Allocator.Persistent);
            kindCursor = new NativeArray<int>(kinds.Length, Allocator.Persistent);
            result = new NativeArray<int>(2, Allocator.Persistent);
            instanceBuffer = new GraphicsBuffer(GraphicsBuffer.Target.Structured, capacity, MobGpu.Stride);

            totalWeight = 0f;
            for (int k = 0; k < kinds.Length; k++)
            {
                KindConfig cfg = kinds[k];
                kindParams[k] = new MobKindParams
                {
                    walkClip = cfg.walkClip,
                    attackClip = cfg.attackClip,
                    deathClip = cfg.deathClip,
                };
                totalWeight += math.max(0f, cfg.spawnWeight);

                cfg.drawMesh = cfg.vat != null && cfg.vat.mesh != null ? cfg.vat.mesh : cfg.mesh;
                cfg.runtimeMaterial = new Material(cfg.material) { name = $"{cfg.material.name} ({cfg.name})" };
                cfg.runtimeMaterial.SetColor(BaseColorId, cfg.tint);
                if (cfg.vat != null && cfg.vat.positions != null)
                {
                    cfg.runtimeMaterial.SetTexture(VatPosId, cfg.vat.positions);
                    cfg.runtimeMaterial.SetTexture(VatNrmId, cfg.vat.normals);
                    cfg.runtimeMaterial.SetVectorArray(VatClipsId, cfg.vat.ShaderClipTable());
                    cfg.runtimeMaterial.SetFloat(UseVatId, 1f);
                }
                else
                {
                    cfg.runtimeMaterial.SetVectorArray(VatClipsId, new Vector4[VatClipSet.MaxClips]);
                    cfg.runtimeMaterial.SetFloat(UseVatId, 0f);
                }
                cfg.props = new MaterialPropertyBlock();
                cfg.props.SetBuffer(MobsId, instanceBuffer);
            }

            KindCounts = new int[kinds.Length];
            rng = new Unity.Mathematics.Random(0x9E3779B9u);
            ready = true;
        }

        // ---------- 외부 API ----------

        /// <summary>영웅 위치 (월드 좌표). 몹은 가장 가까운 영웅을 쫓는다.</summary>
        public void SetHeroes(IList<Vector3> positions, float bodyRadius)
        {
            if (!ready) return;
            heroCount = math.min(positions.Count, MaxHeroes);
            for (int i = 0; i < heroCount; i++)
                heroes[i] = new float3(positions[i].x, positions[i].z, bodyRadius);
        }

        /// <summary>원형 범위 피해. 다음 시뮬레이션 단계에서 적용된다.</summary>
        public void AddHit(Vector3 center, float radius, float damage, float knockback)
        {
            if (pendingHits.Count >= MaxHitsPerFrame) return;
            pendingHits.Add(new HitEvent
            {
                center = new float2(center.x, center.z),
                radius = radius,
                damage = damage,
                knockback = knockback,
            });
        }

        /// <summary>원점 기준 고리 영역에 n마리 생성. 실제 생성 수를 돌려준다.</summary>
        public int Spawn(int n, float minRadius, float maxRadius)
        {
            if (!ready) return 0;
            int added = 0;
            while (added < n && count < capacity)
            {
                int k = PickKind();
                KindConfig cfg = kinds[k];
                float ang = rng.NextFloat(0f, 2f * math.PI);
                float r = rng.NextFloat(minRadius, maxRadius);
                float2 p = new float2(math.cos(ang), math.sin(ang)) * r;
                mobsA[count++] = new MobSim
                {
                    pos = p,
                    vel = float2.zero,
                    yaw = math.atan2(-p.x, -p.y),
                    hp = cfg.hp,
                    speed = cfg.speed * rng.NextFloat(0.85f, 1.15f),
                    radius = cfg.radius,
                    scale = cfg.scale * rng.NextFloat(0.9f, 1.1f),
                    animTime = rng.NextFloat(0f, 4f),
                    kind = k,
                    state = MobState.Walk,
                };
                added++;
            }
            return added;
        }

        /// <summary>몹 수를 n 이하로 즉시 줄인다 (벤치마크용).</summary>
        public void TrimTo(int n)
        {
            if (count > n) count = math.max(0, n);
        }

        int PickKind()
        {
            float x = rng.NextFloat(0f, totalWeight);
            for (int k = 0; k < kinds.Length; k++)
            {
                x -= math.max(0f, kinds[k].spawnWeight);
                if (x <= 0f) return k;
            }
            return 0;
        }

        // ---------- 시뮬레이션 ----------

        void Update()
        {
            if (!ready) return;
            float dt = math.min(Time.deltaTime, 1f / 20f);
            stopwatch.Restart();

            int hitCount = math.min(pendingHits.Count, MaxHitsPerFrame);
            for (int i = 0; i < hitCount; i++) hits[i] = pendingHits[i];
            pendingHits.Clear();

            JobHandle build = new BuildGridJob
            {
                mobs = mobsA,
                count = count,
                grid = grid,
                cellStart = cellStart,
                cellCursor = cellCursor,
                mobCell = mobCell,
                sorted = sorted,
            }.Schedule();

            JobHandle steer = new SteerJob
            {
                input = mobsA,
                cellStart = cellStart,
                sorted = sorted,
                heroes = heroes,
                heroCount = heroCount,
                grid = grid,
                dt = dt,
                attackRange = attackRange,
                accel = acceleration,
                separation = separation,
                deathDuration = deathDuration,
                maxNeighborChecks = maxNeighborChecks,
                output = mobsB,
            }.Schedule(count, 64, build);

            JobHandle damage = new DamageJob
            {
                mobs = mobsB,
                hits = hits,
                hitCount = hitCount,
            }.Schedule(count, 128, steer);

            JobHandle compact = new CompactJob
            {
                input = mobsB,
                count = count,
                output = mobsA,
                gpu = gpuData,
                kinds = kindParams,
                kindCount = kinds.Length,
                kindOffsets = kindOffsets,
                kindCursor = kindCursor,
                result = result,
                deathDuration = deathDuration,
            }.Schedule(damage);

            // 측정 정확도를 위해 즉시 완료. 나중에 LateUpdate 완료로 바꾸면 메인 스레드와 겹칠 수 있다.
            compact.Complete();

            count = result[0];
            gpuCount = count;
            KilledTotal += result[1];
            for (int k = 0; k < kinds.Length; k++) KindCounts[k] = kindOffsets[k + 1] - kindOffsets[k];

            LastSimMs = (float)stopwatch.Elapsed.TotalMilliseconds;
        }

        // ---------- 렌더링 ----------

        void LateUpdate()
        {
            if (!ready || gpuCount == 0) return;
            instanceBuffer.SetData(gpuData, 0, 0, gpuCount);

            var bounds = new Bounds(Vector3.zero, new Vector3(worldHalfSize * 2f, 20f, worldHalfSize * 2f));
            for (int k = 0; k < kinds.Length; k++)
            {
                int n = KindCounts[k];
                KindConfig cfg = kinds[k];
                if (n == 0 || cfg.drawMesh == null) continue;

                cfg.props.SetInteger(OffsetId, kindOffsets[k]);
                var rp = new RenderParams(cfg.runtimeMaterial)
                {
                    worldBounds = bounds,
                    shadowCastingMode = castShadows ? ShadowCastingMode.On : ShadowCastingMode.Off,
                    receiveShadows = true,
                    matProps = cfg.props,
                    layer = gameObject.layer,
                };
                Graphics.RenderMeshPrimitives(rp, cfg.drawMesh, 0, n);
            }
        }

        void OnDestroy()
        {
            ready = false;
            Dispose(ref mobsA); Dispose(ref mobsB); Dispose(ref gpuData);
            Dispose(ref cellStart); Dispose(ref cellCursor); Dispose(ref mobCell); Dispose(ref sorted);
            Dispose(ref heroes); Dispose(ref hits); Dispose(ref kindParams);
            Dispose(ref kindOffsets); Dispose(ref kindCursor); Dispose(ref result);
            instanceBuffer?.Release();
            instanceBuffer = null;
            if (kinds == null) return;
            foreach (KindConfig cfg in kinds)
                if (cfg != null && cfg.runtimeMaterial != null) Destroy(cfg.runtimeMaterial);
        }

        static void Dispose<T>(ref NativeArray<T> a) where T : struct
        {
            if (a.IsCreated) a.Dispose();
        }
    }
}
