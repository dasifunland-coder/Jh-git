using Unity.Burst;
using Unity.Collections;
using Unity.Jobs;
using Unity.Mathematics;

namespace HordeParty.Mobs
{
    /// <summary>균일 격자. 원본의 밀도 그리드에 해당.</summary>
    public struct GridInfo
    {
        public float half;
        public float invCell;
        public int dim;

        public int2 CellXY(float2 p)
        {
            int2 c = (int2)math.floor((p + half) * invCell);
            return math.clamp(c, new int2(0), new int2(dim - 1));
        }

        public int Index(int2 c) => c.y * dim + c.x;
    }

    /// <summary>카운팅 정렬로 셀별 몹 목록을 만든다. O(N + 셀 수). 1만~2만 마리는 단일 스레드로 충분히 빠르다.</summary>
    [BurstCompile]
    public struct BuildGridJob : IJob
    {
        [ReadOnly] public NativeArray<MobSim> mobs;
        public int count;
        public GridInfo grid;
        public NativeArray<int> cellStart;   // 셀 수 + 1
        public NativeArray<int> cellCursor;  // 셀 수
        public NativeArray<int> mobCell;     // 용량
        public NativeArray<int> sorted;      // 용량

        public void Execute()
        {
            int cells = grid.dim * grid.dim;
            for (int c = 0; c <= cells; c++) cellStart[c] = 0;

            for (int i = 0; i < count; i++)
            {
                int c = grid.Index(grid.CellXY(mobs[i].pos));
                mobCell[i] = c;
                cellStart[c + 1] += 1;
            }

            for (int c = 0; c < cells; c++)
            {
                cellCursor[c] = cellStart[c];
                cellStart[c + 1] += cellStart[c];
            }

            for (int i = 0; i < count; i++)
            {
                int c = mobCell[i];
                int k = cellCursor[c];
                sorted[k] = i;
                cellCursor[c] = k + 1;
            }
        }
    }

    /// <summary>가까운 영웅 추적 + 이웃 밀어내기 + 이동 적분. 몹마다 병렬.</summary>
    [BurstCompile]
    public struct SteerJob : IJobParallelFor
    {
        [ReadOnly] public NativeArray<MobSim> input;
        [ReadOnly] public NativeArray<int> cellStart;
        [ReadOnly] public NativeArray<int> sorted;
        [ReadOnly] public NativeArray<float3> heroes; // xy = 바닥 좌표, z = 몸 반지름
        public int heroCount;
        public GridInfo grid;
        public float dt;
        public float attackRange;
        public float accel;
        public float separation;
        public float deathDuration;
        public int maxNeighborChecks;

        [WriteOnly] public NativeArray<MobSim> output;

        public void Execute(int i)
        {
            MobSim m = input[i];
            m.flash = math.max(0f, m.flash - dt * 6f);
            m.animTime += dt;
            m.stateTime += dt;

            if (m.state >= MobState.Dying)
            {
                if (m.stateTime >= deathDuration) m.state = MobState.Dead;
                m.vel *= math.max(0f, 1f - dt * 4f);
                m.pos += m.vel * dt;
                output[i] = m;
                return;
            }

            // 가장 가까운 영웅
            float2 to = -m.pos;
            float bestSq = float.MaxValue;
            float heroR = 0.5f;
            for (int h = 0; h < heroCount; h++)
            {
                float2 d = heroes[h].xy - m.pos;
                float sq = math.lengthsq(d);
                if (sq < bestSq) { bestSq = sq; to = d; heroR = heroes[h].z; }
            }

            float dist = math.length(to);
            float2 dir = dist > 1e-4f ? to / dist : float2.zero;
            float reach = attackRange + heroR + m.radius;
            float2 desired = dist > reach ? dir * m.speed : float2.zero;

            // 이웃 밀어내기 (주변 3x3 셀, 검사 수 상한)
            float2 push = float2.zero;
            int2 c = grid.CellXY(m.pos);
            int checks = 0;
            int y0 = math.max(c.y - 1, 0), y1 = math.min(c.y + 1, grid.dim - 1);
            int x0 = math.max(c.x - 1, 0), x1 = math.min(c.x + 1, grid.dim - 1);
            for (int y = y0; y <= y1 && checks < maxNeighborChecks; y++)
            {
                for (int x = x0; x <= x1 && checks < maxNeighborChecks; x++)
                {
                    int cell = y * grid.dim + x;
                    int end = cellStart[cell + 1];
                    for (int k = cellStart[cell]; k < end && checks < maxNeighborChecks; k++)
                    {
                        int j = sorted[k];
                        if (j == i) continue;
                        MobSim o = input[j];
                        if (o.state >= MobState.Dying) continue;
                        checks++;

                        float2 d = m.pos - o.pos;
                        float r = m.radius + o.radius;
                        float sq = math.lengthsq(d);
                        if (sq >= r * r) continue;
                        if (sq > 1e-8f)
                        {
                            float dd = math.sqrt(sq);
                            push += d / dd * (r - dd);
                        }
                        else
                        {
                            // 완전히 겹친 경우: 인덱스로 결정되는 작은 방향
                            push += new float2((i * 7919 % 13) - 6, (i * 104729 % 11) - 5) * 0.01f;
                        }
                    }
                }
            }

            // 영웅 몸 안으로 들어오지 않게
            float bodyR = heroR + m.radius;
            if (dist < bodyR && dist > 1e-4f) push -= dir * (bodyR - dist);

            float pl = math.length(push);
            if (pl > m.radius) push *= m.radius / pl;

            m.vel = math.lerp(m.vel, desired, math.saturate(dt * accel));
            m.pos += m.vel * dt + push * separation;
            m.pos = math.clamp(m.pos, -grid.half + 0.5f, grid.half - 0.5f);

            if (dist > 1e-4f)
            {
                float targetYaw = math.atan2(dir.x, dir.y);
                m.yaw = LerpAngle(m.yaw, targetYaw, math.saturate(dt * 10f));
            }

            int newState = dist <= reach ? MobState.Attack : MobState.Walk;
            if (newState != m.state)
            {
                m.state = newState;
                m.stateTime = 0f;
                m.animTime = 0f;
            }

            output[i] = m;
        }

        static float LerpAngle(float a, float b, float t)
        {
            float d = b - a;
            d -= math.round(d / (2f * math.PI)) * 2f * math.PI;
            return a + d * t;
        }
    }

    /// <summary>영웅 범위 공격 적용. 몹마다 병렬.</summary>
    [BurstCompile]
    public struct DamageJob : IJobParallelFor
    {
        public NativeArray<MobSim> mobs;
        [ReadOnly] public NativeArray<HitEvent> hits;
        public int hitCount;

        public void Execute(int i)
        {
            if (hitCount == 0) return;
            MobSim m = mobs[i];
            if (m.state >= MobState.Dying) return;

            bool changed = false;
            for (int h = 0; h < hitCount; h++)
            {
                HitEvent e = hits[h];
                float2 d = m.pos - e.center;
                float r = e.radius + m.radius;
                float sq = math.lengthsq(d);
                if (sq > r * r) continue;

                changed = true;
                m.hp -= e.damage;
                m.flash = 1f;
                float len = math.sqrt(sq);
                float2 away = len > 1e-4f ? d / len : float2.zero;
                if (m.hp <= 0f)
                {
                    m.state = MobState.Dying;
                    m.stateTime = 0f;
                    m.animTime = 0f;
                    m.vel = away * e.knockback;
                    break;
                }
                m.vel += away * (e.knockback * 0.35f);
            }

            if (changed) mobs[i] = m;
        }
    }

    /// <summary>
    /// 죽은 몹 제거(순서 유지 압축) + 다음 프레임 입력 배열 작성 + 종류별로 묶은 GPU 인스턴스 데이터 작성.
    /// </summary>
    [BurstCompile]
    public struct CompactJob : IJob
    {
        [ReadOnly] public NativeArray<MobSim> input;
        public int count;
        public NativeArray<MobSim> output;
        public NativeArray<MobGpu> gpu;
        [ReadOnly] public NativeArray<MobKindParams> kinds;
        public int kindCount;
        public NativeArray<int> kindOffsets; // kindCount + 1
        public NativeArray<int> kindCursor;  // kindCount
        public NativeArray<int> result;      // [0] 생존 수, [1] 이번 프레임 제거 수
        public float deathDuration;

        public void Execute()
        {
            for (int k = 0; k <= kindCount; k++) kindOffsets[k] = 0;

            int n = 0, removed = 0;
            for (int i = 0; i < count; i++)
            {
                MobSim m = input[i];
                if (m.state == MobState.Dead) { removed++; continue; }
                output[n++] = m;
                kindOffsets[m.kind + 1] += 1;
            }

            for (int k = 0; k < kindCount; k++)
            {
                kindCursor[k] = kindOffsets[k];
                kindOffsets[k + 1] += kindOffsets[k];
            }

            float sinkStart = math.max(0f, deathDuration - 0.6f);
            for (int i = 0; i < n; i++)
            {
                MobSim m = output[i];
                int k = m.kind;
                int idx = kindCursor[k];
                kindCursor[k] = idx + 1;

                MobKindParams p = kinds[k];
                int clip = m.state == MobState.Walk ? p.walkClip
                         : m.state == MobState.Attack ? p.attackClip
                         : p.deathClip;
                float sink = m.state >= MobState.Dying ? math.max(0f, m.stateTime - sinkStart) * 0.8f * m.scale : 0f;

                gpu[idx] = new MobGpu
                {
                    pos = new float3(m.pos.x, -sink, m.pos.y),
                    yaw = m.yaw,
                    animTime = m.animTime,
                    scale = m.scale,
                    clip = (uint)clip,
                    flash = m.flash,
                };
            }

            result[0] = n;
            result[1] = removed;
        }
    }
}
