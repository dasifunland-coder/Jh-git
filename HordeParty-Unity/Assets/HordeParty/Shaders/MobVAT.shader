// HordeParty 몹 셰이더 (URP).
// - 인스턴스 데이터: StructuredBuffer _Mobs (MobSystem.cs의 MobGpu와 같은 레이아웃)
// - 애니메이션: VAT (SV_VertexID로 위치/노멀 텍스처를 읽음, 프레임 사이 보간)
// - 조명: 메인 라이트 + 그림자 + SH 환경광 + 림 라이트(1만 마리에서도 실루엣이 읽히게) + 피격 플래시 + 안개
// Graphics.RenderMeshPrimitives로 그리며 unity_ObjectToWorld는 쓰지 않는다.
Shader "HordeParty/MobVAT"
{
    Properties
    {
        _BaseColor ("Base Color", Color) = (1, 1, 1, 1)
        _BaseMap ("Base Map", 2D) = "white" {}
        [ToggleUI] _UseVat ("Use VAT", Float) = 1
        [NoScaleOffset] _VatPos ("VAT Positions (RGBAHalf)", 2D) = "black" {}
        [NoScaleOffset] _VatNrm ("VAT Normals (RGBAHalf)", 2D) = "black" {}
        _RimColor ("Rim Color", Color) = (1, 0.45, 0.3, 1)
        _RimPower ("Rim Power", Range(0.5, 8)) = 3
        _RimStrength ("Rim Strength", Range(0, 4)) = 0.8
        _FlashColor ("Hit Flash Color", Color) = (1, 1, 1, 1)
        _Ambient ("Ambient Strength", Range(0, 2)) = 1
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" "Queue" = "Geometry" }

        HLSLINCLUDE
        #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

        struct MobGpu
        {
            float3 pos;
            float yaw;
            float animTime;
            float scale;
            uint clip;
            float flash;
        };

        StructuredBuffer<MobGpu> _Mobs;
        int _InstanceOffset;
        float4 _VatClips[16]; // x 시작 행, y 프레임 수, z fps, w 반복
        TEXTURE2D(_VatPos);
        TEXTURE2D(_VatNrm);
        TEXTURE2D(_BaseMap);
        SAMPLER(sampler_BaseMap);

        CBUFFER_START(UnityPerMaterial)
            float4 _BaseColor;
            float4 _BaseMap_ST;
            float4 _RimColor;
            float4 _FlashColor;
            float _RimPower;
            float _RimStrength;
            float _UseVat;
            float _Ambient;
        CBUFFER_END

        struct MobVertex
        {
            float3 positionWS;
            float3 normalWS;
            float flash;
        };

        void SampleVat(uint vid, uint clip, float t, inout float3 pos, inout float3 nrm)
        {
            float4 c = _VatClips[min(clip, 15u)];
            float frames = max(c.y, 1.0);
            bool loop = c.w > 0.5;
            float f = t * c.z;
            f = loop ? f - frames * floor(f / frames) : min(f, frames - 1.0);
            float f0 = floor(f);
            float f1 = loop ? fmod(f0 + 1.0, frames) : min(f0 + 1.0, frames - 1.0);
            float a = f - f0;
            int2 p0 = int2((int)vid, (int)(c.x + f0));
            int2 p1 = int2((int)vid, (int)(c.x + f1));
            pos = lerp(LOAD_TEXTURE2D_LOD(_VatPos, p0, 0).xyz, LOAD_TEXTURE2D_LOD(_VatPos, p1, 0).xyz, a);
            nrm = normalize(lerp(LOAD_TEXTURE2D_LOD(_VatNrm, p0, 0).xyz, LOAD_TEXTURE2D_LOD(_VatNrm, p1, 0).xyz, a) + 1e-5);
        }

        MobVertex GetMobVertex(float3 positionOS, float3 normalOS, uint vid, uint iid)
        {
            MobGpu m = _Mobs[(uint)_InstanceOffset + iid];
            float3 p = positionOS;
            float3 n = normalOS;
            if (_UseVat > 0.5) SampleVat(vid, m.clip, m.animTime, p, n);

            float s, c;
            sincos(m.yaw, s, c);
            p *= m.scale;

            MobVertex o;
            o.positionWS = float3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z) + m.pos;
            o.normalWS = float3(c * n.x + s * n.z, n.y, -s * n.x + c * n.z);
            o.flash = m.flash;
            return o;
        }
        ENDHLSL

        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" }
            Cull Back
            ZWrite On

            HLSLPROGRAM
            #pragma target 4.5
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE
            #pragma multi_compile_fragment _ _SHADOWS_SOFT _SHADOWS_SOFT_LOW _SHADOWS_SOFT_MEDIUM _SHADOWS_SOFT_HIGH
            #pragma multi_compile_fog
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            struct Attributes
            {
                float3 positionOS : POSITION;
                float3 normalOS : NORMAL;
                float2 uv : TEXCOORD0;
                uint vid : SV_VertexID;
                uint iid : SV_InstanceID;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 positionWS : TEXCOORD0;
                float3 normalWS : TEXCOORD1;
                float2 uv : TEXCOORD2;
                float2 flashFog : TEXCOORD3;
            };

            Varyings vert(Attributes v)
            {
                MobVertex m = GetMobVertex(v.positionOS, v.normalOS, v.vid, v.iid);
                Varyings o;
                o.positionWS = m.positionWS;
                o.normalWS = m.normalWS;
                o.positionCS = TransformWorldToHClip(m.positionWS);
                o.uv = TRANSFORM_TEX(v.uv, _BaseMap);
                o.flashFog = float2(m.flash, ComputeFogFactor(o.positionCS.z));
                return o;
            }

            half4 frag(Varyings i) : SV_Target
            {
                float3 n = normalize(i.normalWS);
                Light light = GetMainLight(TransformWorldToShadowCoord(i.positionWS));
                half3 albedo = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, i.uv).rgb * _BaseColor.rgb;
                half ndl = saturate(dot(n, light.direction));
                half3 col = albedo * (light.color * (ndl * light.shadowAttenuation * light.distanceAttenuation)
                                      + SampleSH(n) * _Ambient);

                float3 viewDir = GetWorldSpaceNormalizeViewDir(i.positionWS);
                half rim = pow(1.0 - saturate(dot(n, viewDir)), _RimPower) * _RimStrength;
                col += rim * _RimColor.rgb;

                col = lerp(col, _FlashColor.rgb, saturate(i.flashFog.x));
                col = MixFog(col, i.flashFog.y);
                return half4(col, 1.0);
            }
            ENDHLSL
        }

        Pass
        {
            Name "ShadowCaster"
            Tags { "LightMode" = "ShadowCaster" }
            ZWrite On
            ZTest LEqual
            ColorMask 0
            Cull Back

            HLSLPROGRAM
            #pragma target 4.5
            #pragma vertex vertShadow
            #pragma fragment fragShadow
            #pragma multi_compile_vertex _ _CASTING_PUNCTUAL_LIGHT_SHADOW
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Shadows.hlsl"

            float3 _LightDirection;
            float3 _LightPosition;

            struct Attributes
            {
                float3 positionOS : POSITION;
                float3 normalOS : NORMAL;
                uint vid : SV_VertexID;
                uint iid : SV_InstanceID;
            };

            float4 vertShadow(Attributes v) : SV_POSITION
            {
                MobVertex m = GetMobVertex(v.positionOS, v.normalOS, v.vid, v.iid);
            #if defined(_CASTING_PUNCTUAL_LIGHT_SHADOW)
                float3 lightDir = normalize(_LightPosition - m.positionWS);
            #else
                float3 lightDir = _LightDirection;
            #endif
                float4 cs = TransformWorldToHClip(ApplyShadowBias(m.positionWS, normalize(m.normalWS), lightDir));
            #if UNITY_REVERSED_Z
                cs.z = min(cs.z, UNITY_NEAR_CLIP_VALUE);
            #else
                cs.z = max(cs.z, UNITY_NEAR_CLIP_VALUE);
            #endif
                return cs;
            }

            half4 fragShadow() : SV_Target { return 0; }
            ENDHLSL
        }

        Pass
        {
            Name "DepthOnly"
            Tags { "LightMode" = "DepthOnly" }
            ZWrite On
            ColorMask R
            Cull Back

            HLSLPROGRAM
            #pragma target 4.5
            #pragma vertex vertDepth
            #pragma fragment fragDepth

            struct Attributes
            {
                float3 positionOS : POSITION;
                float3 normalOS : NORMAL;
                uint vid : SV_VertexID;
                uint iid : SV_InstanceID;
            };

            float4 vertDepth(Attributes v) : SV_POSITION
            {
                MobVertex m = GetMobVertex(v.positionOS, v.normalOS, v.vid, v.iid);
                return TransformWorldToHClip(m.positionWS);
            }

            half fragDepth() : SV_Target { return 0; }
            ENDHLSL
        }

        Pass
        {
            Name "DepthNormals"
            Tags { "LightMode" = "DepthNormals" }
            ZWrite On
            Cull Back

            HLSLPROGRAM
            #pragma target 4.5
            #pragma vertex vertDN
            #pragma fragment fragDN
            #pragma multi_compile_fragment _ _GBUFFER_NORMALS_OCT

            struct Attributes
            {
                float3 positionOS : POSITION;
                float3 normalOS : NORMAL;
                uint vid : SV_VertexID;
                uint iid : SV_InstanceID;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 normalWS : TEXCOORD0;
            };

            Varyings vertDN(Attributes v)
            {
                MobVertex m = GetMobVertex(v.positionOS, v.normalOS, v.vid, v.iid);
                Varyings o;
                o.positionCS = TransformWorldToHClip(m.positionWS);
                o.normalWS = m.normalWS;
                return o;
            }

            half4 fragDN(Varyings i) : SV_Target
            {
                float3 n = normalize(i.normalWS);
            #if defined(_GBUFFER_NORMALS_OCT)
                float2 oct = PackNormalOctQuadEncode(n);
                float2 remapped = saturate(oct * 0.5 + 0.5);
                return half4(PackFloat2To888(remapped), 0.0);
            #else
                return half4(n, 0.0);
            #endif
            }
            ENDHLSL
        }
    }

    FallBack Off
}
