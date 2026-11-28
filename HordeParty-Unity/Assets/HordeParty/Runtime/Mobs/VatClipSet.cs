using System;
using UnityEngine;

namespace HordeParty.Mobs
{
    /// <summary>
    /// 버텍스 애니메이션 텍스처(VAT) 묶음.
    /// positions/normals: 가로 = 버텍스 번호, 세로 = 프레임(모든 클립을 이어 붙임). RGBAHalf, 오브젝트 공간.
    /// </summary>
    [CreateAssetMenu(menuName = "HordeParty/VAT Clip Set")]
    public class VatClipSet : ScriptableObject
    {
        public const int MaxClips = 16;

        [Serializable]
        public struct Clip
        {
            public string name;
            public int startRow;
            public int frameCount;
            public float fps;
            public bool loop;
        }

        public Mesh mesh;
        public Texture2D positions;
        public Texture2D normals;
        public Clip[] clips = Array.Empty<Clip>();

        /// <summary>셰이더 _VatClips 배열용: x = 시작 행, y = 프레임 수, z = fps, w = 반복 여부.</summary>
        public Vector4[] ShaderClipTable()
        {
            var table = new Vector4[MaxClips];
            for (int i = 0; i < clips.Length && i < MaxClips; i++)
            {
                Clip c = clips[i];
                table[i] = new Vector4(c.startRow, c.frameCount, c.fps, c.loop ? 1f : 0f);
            }
            return table;
        }

        public int IndexOf(string clipName)
        {
            for (int i = 0; i < clips.Length; i++)
                if (string.Equals(clips[i].name, clipName, StringComparison.OrdinalIgnoreCase)) return i;
            return -1;
        }
    }
}
