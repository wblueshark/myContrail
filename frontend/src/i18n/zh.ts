/**
 * User-facing copy.
 *
 * The product's interface language is Chinese, but every identifier, comment
 * and log line in this codebase is English. Keeping all display strings in this
 * one data module preserves both: components reference English keys, and the
 * only CJK text in the frontend lives here, where it is content rather than
 * code. Swapping languages means adding a sibling file.
 */

export const t = {
  app: {
    name: 'Contrail',
    tagline: '你的位置历史，只属于你',
    loading: '加载中…',
    empty: '暂无数据',
    retry: '重试',
    cancel: '取消',
    confirm: '确认',
    save: '保存',
    delete: '删除',
    close: '关闭',
    unknown: '未知',
  },

  nav: {
    map: '地图',
    timeline: '时间轴',
    trips: '行程',
    groups: '分组与标签',
    commute: '通勤',
    sources: '数据源',
    settings: '设置',
  },

  connection: {
    tokenTitle: '需要本机访问令牌',
    tokenHelp:
      '首次启动时后端会把令牌写入 ~/.contrail/token。这道护栏挡住的是同机其他进程调用 API —— 只绑定 127.0.0.1 并不安全。',
    tokenPlaceholder: '粘贴 ~/.contrail/token 的内容',
    tokenSubmit: '连接',
    tokenInvalid: '令牌无效，请检查 ~/.contrail/token',
    backendDown: '连接不上后端。请确认 uvicorn 已在 127.0.0.1:8000 运行。',
    mapboxMissing: 'Mapbox token 未配置，底图不会显示。库内数据与空间查询不受影响。',
  },

  filters: {
    title: '筛选',
    search: '搜索地点或行程',
    time: '时间',
    timeAll: '全部',
    timeThisYear: '今年',
    timeCustom: '自定义',
    layers: '图层',
    layerTracks: '轨迹',
    layerPlaces: '停留点',
    layerPhotos: '照片',
    layerHeatmap: '热力图',
    modes: '交通方式',
    sources: '数据源',
    groups: '分组',
    tags: '标签',
    fenceNotice: (n: number) => `隐私围栏：已配置 ${n} 处`,
    fenceNone: '尚未设置隐私围栏',
    reset: '重置筛选',
  },

  modes: {
    walk: '步行',
    run: '跑步',
    bike: '骑行',
    car: '驾车',
    transit: '公共交通',
    flight: '飞行',
    unknown: '未知',
  },

  sourceKinds: {
    photo: '照片',
    google_records: 'Google 原始点',
    google_semantic: 'Google 语义时间线',
    google_timeline: 'Google 时间线',
    gpx: 'GPX',
    tcx: 'TCX',
    fit: 'FIT',
    manual: '手动',
  },

  detail: {
    place: '地点',
    track: '路途',
    photo: '照片',
    trip: '所属行程',
    openTrip: '打开行程',
    duration: '停留时长',
    distance: '距离',
    distanceUnknown: '距离未知',
    speed: '速度中位数',
    mode: '交通方式',
    modeUncertain: '推断置信度较低',
    dataSource: '数据来源',
    photoCount: (n: number) => `${n} 张照片`,
    viewAll: '查看全部',
    // P4: a dwell partly deduced from a data gap must never look measured.
    inferredDwell: (pct: number) => `其中约 ${pct}% 的时长由数据空隙推断`,
    inferredLocation: '位置为推断',
    endpointsOnly: '仅有起终点，路线为直线示意',
    crossesTz: '跨时区',
  },

  timeline: {
    title: '时间轴',
    year: '年',
    month: '月',
    day: '日',
    activityDensity: '活动密度',
    noData: '这段时间没有数据',
  },

  trips: {
    title: '行程',
    count: (n: number) => `共 ${n} 个行程`,
    places: (n: number) => `${n} 个地点`,
    tracks: (n: number) => `${n} 段路途`,
    photos: (n: number) => `${n} 张照片`,
    photoOnly: '仅照片，无停留时长',
    rename: '重命名',
    assignGroup: '改分组',
    addTag: '加标签',
    export: '导出图片',
    // P7: the boundary between algorithm-owned content and user-owned metadata.
    editableNotice:
      '标题、分组和标签可以随时修改。地点、路途、时间和归属日由算法产出，本版本不支持手动订正。',
    unknownDistanceHint: (n: number) => `其中 ${n} 段距离未知，总里程为下限`,
  },

  groups: {
    title: '分组与标签',
    groups: '分组（互斥，每项最多一个）',
    tags: '标签（可多选）',
    newGroup: '新建分组',
    newTag: '新建标签',
    systemGroup: '系统分组，不可删除',
    tripCount: (n: number) => `${n} 个行程`,
    nameExists: '同名已存在',
  },

  commute: {
    title: '通勤',
    detected: (n: number) => `识别出 ${n} 组通勤路线`,
    coldStart: (have: number, need: number) =>
      `数据还太少（有数据的工作日 ${have} 天，需要 ${need} 天），暂时无法识别日常通勤。继续导入更多历史数据后会自动重新分析。`,
    evidence: '判定依据',
    occurrence: (n: number) => `出现 ${n} 次`,
    weekdayRatio: (pct: number) => `工作日占比 ${pct}%`,
    departHour: (hour: string, std: string) => `出发时刻集中在 ${hour}（波动 ±${std}）`,
    pathStability: (pct: number) => `路径重合度 ${pct}%`,
    sampleDates: '样例日期',
    medianDistance: '典型里程',
    classPure: '纯通勤日',
    classMixed: '含通勤',
    actionCollapse: '在地图上折叠',
    actionToNormal: '转为普通行程',
    actionDelete: '删除行程',
    // Only a pure day is deletable; the reason has to be visible, not implied.
    mixedNotDeletable: (places: number, photos: number) =>
      `这一天还有 ${places} 处其他地点和 ${photos} 张照片，不能整体删除。只能折叠其中的通勤路途。`,
    deleteWarning: '删除的是派生数据。原始文件已保留，重新导入即可恢复。',
    recompute: '用当前参数重新识别',
  },

  sources: {
    title: '数据源',
    importPhotos: '导入照片',
    importFile: '导入轨迹文件',
    chooseFolder: '选择照片目录',
    // v2.3: no scan roots are ever persisted, which is what makes "read once" a
    // structural guarantee rather than a promise.
    chooseFolderHelp:
      '会打开系统的目录选择框。选中的目录只在导入时读取一次，之后产品永不再访问它 —— 系统里根本不保存扫描目录。',
    pickerUnavailable: '当前环境没有系统目录选择器，照片导入不可用。',
    cancelled: '已取消选择',
    prescanResult: (files: number, gps: number) =>
      `共发现 ${files} 个文件，抽样中 ${gps}% 带 GPS`,
    prescanEstimate: (seconds: number) => `预计耗时约 ${Math.max(1, Math.round(seconds))} 秒`,
    largeWarning: (files: number) =>
      `这个目录有 ${files} 个文件，导入会花较长时间。确认要继续吗？`,
    dropFile: '把 GPX / TCX / FIT / Google 时间线文件拖到这里，或点击选择',
    detected: (kind: string) => `识别为：${kind}`,
    batchGroup: '本批次分组',
    batchTags: '本批次标签',
    noGroup: '不分组',
    startImport: '开始导入',
    importing: '导入中',
    imported: '已导入文件',
    undo: '撤销导入',
    undoWarning: '会删除这个来源的数据并重算受影响的时间范围。',
    originalKept: '已保留原始文件',
    status: '状态',
    stage: {
      sniffing: '识别格式',
      parsing: '解析中',
      persisting: '入库中',
      photos: '处理照片',
      scanning: '扫描目录',
      deriving: '生成行程',
      done: '完成',
    },
    // Totals are unknown while streaming, so an absolute count is shown.
    progress: (done: number, total: number | null) =>
      total === null ? `已处理 ${done}` : `${done} / ${total}`,
    alreadyImported: '这个文件已经导入过了，跳过。',
    reportTitle: '导入完成',
    reportCreated: (n: number, group: string) => `新建 ${n} 个行程 → 分组「${group}」`,
    // Existing trips keep their group: a day can be built from several imports.
    reportExisting: (n: number) => `${n} 个行程已存在，分组保持不变，已追加本批次标签`,
    reportPoints: (n: number) => `写入 ${n} 个位置点`,
    reportPhotos: (n: number) => `导入 ${n} 张照片`,
    reportDuplicates: (n: number) => `跳过 ${n} 张重复照片`,
    reportSkipped: '跳过的记录',
    reportErrors: '错误',
    failed: '导入失败',
  },

  settings: {
    title: '设置',
    fences: '隐私围栏',
    clustering: '停留点聚类',
    commuteParams: '通勤识别',
    map: '地图',
    geocoding: '反向地理编码',
    account: '账号',
    accountReserved: '本版本为本机单用户，无需登录。',
    radius: '漫游半径 R（米）',
    minDwell: '最小停留时长 T（秒）',
    gap: '数据缺失阈值 GAP（秒）',
    accuracyMax: '精度过滤上限（米）',
    photoTolerance: '照片位置推断时间容差（秒）',
    presets: '场景预设',
    presetCity: '城市观光',
    presetLongDrive: '长途驾车',
    presetHiking: '徒步露营',
    presetCoarse: '粗粒度概览',
    recluster: '用新参数重算',
    reclusterHelp: '会重新生成地点、路途和行程。原始数据不受影响。',
    geocodingOn: '开启（只对地点锚点请求，约几百次）',
    geocodingOff: '关闭（完全不联网。地名留空，地图与空间查询照常可用）',
    dataExport: '导出全部数据',
    dataExportHelp: 'GeoJSON + GPX 打包下载。这是你自己的数据，不做围栏裁剪。',
  },

  fences: {
    title: '隐私围栏',
    // Every historical address is a fence, always active - a "current home only"
    // fence leaks the old address the moment a past year is exported.
    intro:
      '围栏内的坐标不会出现在导出的图片里。所有历史住址和公司全部作为围栏、全时段生效 —— 导出往年足迹时，当年的住址同样被保护。',
    suggestions: '根据你的数据推算出的建议',
    tierConfirmed: 'Google 已确认',
    tierInferred: 'Google 推断的',
    tierHeuristic: '我们统计出来的',
    // The three tiers are never merged: confirmed and inferred were measured
    // hundreds of metres apart and are different places.
    tierHelp:
      '这三类要分别确认。实测「Google 确认的家」与「Google 推断的家」相距数百米，是不同的地方 —— 只确认其中一个，另一处完全没有被保护。',
    visitSummary: (count: number, from: string, to: string) => `到访 ${count} 次 · ${from}–${to}`,
    alreadyFenced: '已有围栏',
    addFence: '加为围栏',
    kindHome: '住宅',
    kindWork: '公司',
    label: '备注',
    radius: '半径（米）',
    enabled: '启用',
    empty: '还没有围栏。导入数据后这里会给出建议。',
    offlineNote: '住址推算完全离线，不会把你的地址发给任何第三方。',
  },

  exportPanel: {
    title: '导出图片',
    template: '模板',
    templateMap: '纯地图',
    templatePoster: '海报',
    templateCollage: '照片拼贴',
    size: '尺寸',
    theme: '主题',
    themeLight: '浅色',
    themeDark: '深色',
    preview: '预览',
    previewing: '生成预览…',
    download: '导出 PNG',
    exporting: '渲染中…',
    nothingSelected: '先选择要导出的行程或地点',
    attribution: '版权署名会出现在图片右下角，不可关闭。',
    // Blocking dialog: the server refuses an intersecting export without a
    // choice, so this is a decision point rather than a warning.
    fenceTitle: '这次导出的范围内有隐私围栏',
    fenceBody: (fences: number, places: number, tracks: number) =>
      `涉及 ${fences} 处围栏，影响 ${places} 个地点和 ${tracks} 段路途。请选择处理方式：`,
    fenceBlur: '模糊',
    fenceBlurHelp: '把围栏附近的位置粗化到约 2 公里网格，并裁掉仍落在围栏内的部分。',
    fenceRemove: '删除',
    fenceRemoveHelp: '直接裁掉围栏内的轨迹与地点，并对断点做扰动，避免反推出圆心。',
    fenceRequired: '必须选择一种处理方式才能导出。',
  },

  stats: {
    title: '统计',
    trips: '行程',
    distance: '总里程',
    countries: '国家',
    cities: '城市',
    places: '地点',
    photos: '照片',
    // Honesty requirement: unknown mileage is reported, never counted as zero.
    unknownDistance: (n: number) => `另有 ${n} 段距离未知，未计入总里程`,
    inferredDwell: (n: number) => `${n} 处停留的时长部分由推断得出`,
    inferredPhotos: (n: number) => `${n} 张照片的位置是推断的`,
    unlocatedPhotos: (n: number) => `${n} 张照片没有位置`,
    geocodingOff: '反向地理编码已关闭，国家与城市统计不可用。',
  },
} as const

export type Copy = typeof t
