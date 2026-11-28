using System.Runtime.InteropServices;
using Unity.Mathematics;

namespace HordeParty.Mobs
{
    /// <summary>몹 상태값. Godot mob_system.gd의 상태 플래그에 대응.</summary>
    public static class MobState
    {
        public const int Walk = 0;
        public const int Attack = 1;
        public const int Dying = 2;
        public const int Dead = 3;
    }

    /// <summary>
    /// CPU 시뮬레이션용 몹 데이터 (Godot의 Packed 배열 한 칸에 해당).
    /// pos/vel은 바닥 평면 좌표: x = 월드 X, y = 월드 Z.
    /// </summary>
    public struct MobSim
    {
        public float2 pos;
        public float2 vel;
        public float yaw;
        public float hp;
        public float speed;
        public float radius;
        public float scale;
        public float animTime;
        public float stateTime;
        public float flash;
        public int kind;
        public int state;
    }

    /// <summary>GPU로 올리는 인스턴스 데이터. 셰이더의 MobGpu와 레이아웃이 같아야 한다 (32바이트).</summary>
    [StructLayout(LayoutKind.Sequential)]
    public struct MobGpu
    {
        public float3 pos;
        public float yaw;
        public float animTime;
        public float scale;
        public uint clip;
        public float flash;

        public const int Stride = 32;
    }

    /// <summary>종류별로 잡(Job)에 넘기는 값.</summary>
    public struct MobKindParams
    {
        public int walkClip;
        public int attackClip;
        public int deathClip;
    }

    /// <summary>영웅 공격 한 번 (원형 범위 피해).</summary>
    public struct HitEvent
    {
        public float2 center;
        public float radius;
        public float damage;
        public float knockback;
    }
}
