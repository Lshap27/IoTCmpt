export type DemoDorm = {
  id: string;
  floor: string;
  room: string;
  temp: number;
  hum: number;
  co2: number;
  formaldehyde: number;
  tvoc: number;
  mq2: number;
  windowOpen: boolean;
  lightOn: boolean;
  fanOn: boolean;
  deviceOnline: boolean;
  inRoom: number;
  score: number;
  scoreDetail: {
    ventilation: number;
    energy: number;
    safety: number;
    health: number;
  };
};

export type DemoAlert = {
  dorm: string;
  type: string;
  level: "一级轻微" | "二级中度" | "三级高危";
  time: string;
  duration: string;
  value: string;
  threshold: string;
  status: "未处理" | "已处置";
};

export type DemoNotification = {
  id: string;
  time: string;
  target: string;
  content: string;
  status: string;
  count: number;
};

export const DEMO_ALERTS: DemoAlert[] = [
  {
    dorm: "映雪3-512",
    type: "MQ2燃气超标",
    level: "三级高危",
    time: "2026-07-09 15:32",
    duration: "45分钟",
    value: "820ppm",
    threshold: "500ppm",
    status: "未处理",
  },
  {
    dorm: "映雪3-408",
    type: "高温预警",
    level: "三级高危",
    time: "2026-07-09 14:18",
    duration: "1小时20分",
    value: "35.6°C",
    threshold: "35°C",
    status: "未处理",
  },
  {
    dorm: "映雪3-305",
    type: "CO₂严重超标",
    level: "三级高危",
    time: "2026-07-09 12:05",
    duration: "5小时",
    value: "2100ppm",
    threshold: "1500ppm",
    status: "未处理",
  },
  {
    dorm: "映雪3-407",
    type: "甲醛超标",
    level: "二级中度",
    time: "2026-07-09 11:40",
    duration: "6小时",
    value: "0.14mg/m³",
    threshold: "0.1mg/m³",
    status: "已处置",
  },
  {
    dorm: "映雪3-502",
    type: "CO₂超标",
    level: "一级轻微",
    time: "2026-07-09 10:15",
    duration: "8小时",
    value: "1680ppm",
    threshold: "1500ppm",
    status: "已处置",
  },
  {
    dorm: "映雪3-309",
    type: "高湿预警",
    level: "一级轻微",
    time: "2026-07-09 09:22",
    duration: "9小时",
    value: "89%",
    threshold: "85%",
    status: "已处置",
  },
  {
    dorm: "映雪3-511",
    type: "甲醛超标",
    level: "二级中度",
    time: "2026-07-09 08:50",
    duration: "10小时",
    value: "0.12mg/m³",
    threshold: "0.1mg/m³",
    status: "已处置",
  },
  {
    dorm: "映雪3-303",
    type: "CO₂超标",
    level: "一级轻微",
    time: "2026-07-09 07:30",
    duration: "11小时",
    value: "1550ppm",
    threshold: "1500ppm",
    status: "已处置",
  },
];

export const DEMO_NOTIFICATIONS: DemoNotification[] = [
  {
    id: "demo-notice-1",
    time: "2026-07-09 15:30",
    target: "映雪3-512",
    content: "燃气浓度超标，请立即关闭燃气阀门，打开门窗通风！",
    status: "已送达",
    count: 1,
  },
  {
    id: "demo-notice-2",
    time: "2026-07-09 14:20",
    target: "映雪3-408",
    content: "室内温度过高，请开启空调或风扇降温。",
    status: "已送达",
    count: 1,
  },
  {
    id: "demo-notice-3",
    time: "2026-07-09 08:00",
    target: "整栋(180间)",
    content: "同学们早上好，今天有阵雨，出门请带伞。今日查寝安排在22:00。",
    status: "已送达",
    count: 178,
  },
  {
    id: "demo-notice-4",
    time: "2026-07-08 22:00",
    target: "映雪3-4层(30间)",
    content: "查寝时间到了，请各位同学回到宿舍，配合查寝工作。",
    status: "已送达",
    count: 30,
  },
  {
    id: "demo-notice-5",
    time: "2026-07-08 16:00",
    target: "映雪3-5层(30间)",
    content: "文明宿舍评比即将开始，请大家保持宿舍整洁卫生！",
    status: "已送达",
    count: 29,
  },
];

export const MAINTENANCE_ORDERS = [
  {
    id: "WO-20260709-001",
    dorm: "映雪3-305",
    device: "排风扇舵机",
    desc: "排风扇无法启动，电机无响应",
    time: "2026-07-09 12:05",
    status: "待维修",
    staff: "-",
  },
  {
    id: "WO-20260708-002",
    dorm: "映雪3-410",
    device: "MQ2燃气传感器",
    desc: "传感器数据异常，持续报0",
    time: "2026-07-08 09:30",
    status: "维修中",
    staff: "王师傅",
  },
  {
    id: "WO-20260707-003",
    dorm: "映雪3-508",
    device: "门磁传感器",
    desc: "开关门检测异常，数据不更新",
    time: "2026-07-07 14:20",
    status: "维修中",
    staff: "李师傅",
  },
];

const ROOMS = [
  "301",
  "302",
  "303",
  "304",
  "305",
  "306",
  "307",
  "308",
  "309",
  "310",
  "401",
  "402",
  "403",
  "404",
  "405",
  "406",
  "407",
  "408",
  "409",
  "410",
  "501",
  "502",
  "503",
  "504",
  "505",
  "506",
  "507",
  "508",
  "509",
  "510",
];

export const DEMO_DORMS: DemoDorm[] = ROOMS.map((room, index) => ({
  id: `映雪3-${room}`,
  floor: room[0],
  room,
  temp: Number((24 + ((index * 17) % 115) / 10).toFixed(1)),
  hum: 42 + ((index * 11) % 47),
  co2: 520 + ((index * 137) % 1660),
  formaldehyde: Number((0.018 + ((index * 9) % 125) / 1000).toFixed(3)),
  tvoc: Number((0.08 + ((index * 13) % 72) / 100).toFixed(2)),
  mq2: index === 4 ? 560 : index === 21 ? 820 : 0,
  windowOpen: index % 5 !== 0,
  lightOn: index % 3 === 0,
  fanOn: index % 4 < 2,
  deviceOnline: index !== 9,
  inRoom: index % 5,
  score: 62 + ((index * 7) % 37),
  scoreDetail: {
    ventilation: 61 + ((index * 9) % 38),
    energy: 52 + ((index * 11) % 47),
    safety: 70 + ((index * 5) % 29),
    health: 44 + ((index * 13) % 55),
  },
}));

export const IOT_DEMO_DORMS = DEMO_DORMS.slice(1, 6);
