import { ImageResponse } from "next/og";

export const alt = "Balanced Portfolio — 风险平价组合管理与回测";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          background: "#0A0A0A",
          color: "#EDEDED",
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          justifyContent: "center",
          padding: "0 90px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 24, marginBottom: 28 }}>
          <div
            style={{
              width: 72,
              height: 72,
              background: "#3B82F6",
              color: "white",
              fontSize: 38,
              fontWeight: 700,
              borderRadius: 16,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            BP
          </div>
          <div style={{ fontSize: 40, fontWeight: 600, color: "#A1A1A1" }}>Balanced Portfolio</div>
        </div>
        <div style={{ fontSize: 76, fontWeight: 700, lineHeight: 1.1, letterSpacing: -1 }}>
          风险平价组合
        </div>
        <div style={{ fontSize: 76, fontWeight: 700, lineHeight: 1.1, letterSpacing: -1 }}>
          管理与回测平台
        </div>
        <div style={{ fontSize: 30, color: "#A1A1A1", marginTop: 32 }}>
          桥水达利欧四象限 · 四种优化方法 · 无未来函数回测
        </div>
      </div>
    ),
    { ...size }
  );
}
