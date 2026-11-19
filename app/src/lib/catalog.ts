import type { Catalog, TrackId } from '../types'

/** Used until /api/catalog answers, and in mock mode. Same content as the example in docs/api.md. */
export const DEFAULT_CATALOG: Catalog = {
  instruments: {
    vocal: [{ id: 'synth-male', label: '男声' }, { id: 'synth-female', label: '女声' }, { id: 'synth-soft', label: '轻声' }],
    melody: [{ id: 'harmonica', label: '口琴' }, { id: 'piano', label: '钢琴' }, { id: 'whistle', label: '口哨' }, { id: 'flute', label: '长笛' }],
    guitar: [{ id: 'steel', label: '木吉他' }, { id: 'nylon', label: '尼龙吉他' }, { id: 'electric-clean', label: '电吉他（干净）' }, { id: 'ukulele', label: '尤克里里' }],
    bass: [{ id: 'finger-bass', label: '指弹贝斯' }, { id: 'upright-bass', label: '低音提琴' }, { id: 'synth-bass', label: '合成器贝斯' }],
    drums: [{ id: 'jazz-kit', label: '爵士鼓' }, { id: 'pop-kit', label: '流行鼓' }, { id: 'hand-drum', label: '手鼓' }],
    ambience: [{ id: 'recording', label: '原声' }],
  },
  styles: {
    vocal: [{ id: 'plain', label: '只唱主旋律' }, { id: 'harmony', label: '加一层和声' }],
    melody: [{ id: 'follow', label: '跟着人声' }, { id: 'answer', label: '人声停时才出来' }],
    guitar: [{ id: 'strum', label: '扫弦' }, { id: 'arpeggio', label: '分解和弦' }, { id: 'muted', label: '闷音扫弦' }, { id: 'sustain', label: '只弹长音' }],
    bass: [{ id: 'sustain', label: '长音' }, { id: 'groove', label: '跟着鼓点' }, { id: 'walking', label: '走动' }],
    drums: [{ id: 'brush', label: '刷子' }, { id: 'sticks', label: '鼓棒' }, { id: 'hand', label: '只有手鼓' }],
    ambience: [{ id: 'recording', label: '原声' }, { id: 'soft', label: '柔和一点' }],
  },
  spaces: [{ id: 'dry', label: '干净' }, { id: 'room', label: '房间' }, { id: 'hall', label: '大厅' }],
  cardStyles: ['ink', 'comic', 'xieyi', 'original', 'text'],
}

export const labelOf = (list: { id: string; label: string }[] | undefined, id: string) => list?.find((x) => x.id === id)?.label ?? ''
export const instrumentLabel = (cat: Catalog, track: TrackId, id: string) => labelOf(cat.instruments[track], id) || labelOf(DEFAULT_CATALOG.instruments[track], id) || '默认音色'
export const styleLabel = (cat: Catalog, track: TrackId, id: string) => labelOf(cat.styles[track], id) || labelOf(DEFAULT_CATALOG.styles[track], id) || ''

/** What the pad's edges mean for each player, in plain words: [soft, loud, simple, busy]. */
export const PAD_WORDS: Record<TrackId, [string, string, string, string]> = {
  vocal: ['轻声', '用力', '平实', '花哨'],
  melody: ['轻', '响', '简单', '多装饰'],
  guitar: ['轻', '响', '简单', '复杂'],
  bass: ['轻', '响', '简单', '走动多'],
  drums: ['轻', '响', '简单', '复杂'],
  ambience: ['远', '近', '平稳', '起伏'],
}
export const STYLE_TITLE: Record<TrackId, string> = { vocal: '嗓音', melody: '怎么吹拉弹', guitar: '弹法', bass: '弹法', drums: '打法', ambience: '声音' }
