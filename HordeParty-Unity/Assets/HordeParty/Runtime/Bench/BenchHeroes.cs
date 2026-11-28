using System.Collections.Generic;
using HordeParty.Mobs;
using UnityEngine;

namespace HordeParty.Bench
{
    /// <summary>
    /// 기술 검증용 임시 영웅 5명. 중앙에서 원을 그리며 돌고, 직업별 주기로 범위 피해를 넣어
    /// 사망 → 제거 → 재생성 흐름이 1만 마리 규모에서 계속 돌게 한다. 실제 전투는 4단계에서 만든다.
    /// </summary>
    [DefaultExecutionOrder(-40)]
    public class BenchHeroes : MonoBehaviour
    {
        public MobSystem mobs;
        public Material heroMaterial;
        public float orbitRadius = 4f;
        public float orbitSpeed = 0.35f;
        public float bodyRadius = 0.6f;
        public bool attack = true;
        public float damageScale = 1f;

        class Hero
        {
            public string name;
            public Color color;
            public float interval, radius, damage, reach, knockback;
            public float timer;
            public Transform tr;
        }

        Hero[] party;
        readonly List<Vector3> positions = new List<Vector3>();
        static readonly int BaseColorId = Shader.PropertyToID("_BaseColor");

        void Start()
        {
            party = new[]
            {
                new Hero { name = "Warrior", color = new Color(0.85f, 0.25f, 0.2f), interval = 0.55f, radius = 2.6f, damage = 30f, reach = 0f, knockback = 6f },
                new Hero { name = "Archer", color = new Color(0.3f, 0.75f, 0.3f), interval = 0.22f, radius = 0.9f, damage = 22f, reach = 16f, knockback = 2f },
                new Hero { name = "Mage", color = new Color(0.35f, 0.45f, 0.95f), interval = 1.1f, radius = 4.5f, damage = 60f, reach = 22f, knockback = 8f },
                new Hero { name = "Rogue", color = new Color(0.6f, 0.3f, 0.75f), interval = 0.16f, radius = 1.3f, damage = 16f, reach = 2.2f, knockback = 3f },
                new Hero { name = "Paladin", color = new Color(0.95f, 0.8f, 0.3f), interval = 0.8f, radius = 3.0f, damage = 35f, reach = 1.5f, knockback = 7f },
            };

            var mpb = new MaterialPropertyBlock();
            foreach (Hero h in party)
            {
                GameObject go = GameObject.CreatePrimitive(PrimitiveType.Capsule);
                go.name = h.name;
                Destroy(go.GetComponent<Collider>());
                go.transform.SetParent(transform, false);
                var r = go.GetComponent<Renderer>();
                if (heroMaterial != null) r.sharedMaterial = heroMaterial;
                mpb.SetColor(BaseColorId, h.color);
                r.SetPropertyBlock(mpb);
                h.tr = go.transform;
                h.timer = Random.value * h.interval;
            }
        }

        void Update()
        {
            if (party == null || mobs == null) return;
            positions.Clear();
            float t = Time.time;
            for (int i = 0; i < party.Length; i++)
            {
                Hero h = party[i];
                float a = t * orbitSpeed + i * (Mathf.PI * 2f / party.Length);
                var p = new Vector3(Mathf.Cos(a) * orbitRadius, 0f, Mathf.Sin(a) * orbitRadius);
                h.tr.position = p + Vector3.up;
                positions.Add(p);

                if (!attack) continue;
                h.timer -= Time.deltaTime;
                while (h.timer <= 0f)
                {
                    h.timer += h.interval;
                    float ang = Random.value * Mathf.PI * 2f;
                    Vector3 dir = new Vector3(Mathf.Cos(ang), 0f, Mathf.Sin(ang));
                    Vector3 center = p + dir * (h.reach * Random.Range(0.5f, 1f));
                    mobs.AddHit(center, h.radius, h.damage * damageScale, h.knockback);
                }
            }
            mobs.SetHeroes(positions, bodyRadius);
        }
    }
}
