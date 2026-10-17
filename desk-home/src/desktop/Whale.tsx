/**
 * 角落像素鲸鱼：纯 CSS box-shadow 手绘，4px 网格。
 * 职责只有"待在那儿"——不聊天、不推销、不抢戏。
 */
export function Whale() {
  return (
    <div
      className="whale"
      style={{
        bottom: 100,
        boxShadow: [
          '12px 0 0 var(--whale)', '16px 0 0 var(--whale)',
          '8px 4px 0 var(--whale)', '12px 4px 0 var(--whale)', '16px 4px 0 var(--whale)', '20px 4px 0 var(--whale)',
          '-4px 8px 0 var(--whale)',
          '0 8px 0 var(--whale)', '4px 8px 0 #fff', '8px 8px 0 var(--whale)', '12px 8px 0 var(--whale)', '16px 8px 0 var(--whale)', '20px 8px 0 #26303B',
          '0 12px 0 var(--whale)', '4px 12px 0 #fff', '8px 12px 0 #fff', '12px 12px 0 var(--whale)', '16px 12px 0 var(--whale)',
          '4px 16px 0 var(--whale)', '8px 16px 0 var(--whale)', '12px 16px 0 #fff', '16px 16px 0 var(--whale)',
          '8px 20px 0 var(--whale)', '12px 20px 0 var(--whale)',
        ].join(','),
      }}
      aria-hidden
    >
      <i className="whale__bubble" style={{ left: 15, top: -4 }} />
      <i className="whale__bubble whale__bubble--2" style={{ left: 21, top: -9 }} />
    </div>
  )
}
