# クリップ作成支援ツール

## 環境構築

### Ubuntu
```
sudo apt update && sudo bash setup.sh
```

## 起動
```
python main.py
```

## アクセス
```
http://localhost:8866/
```

## 切り抜きの保存先

- clips以下
    - .mp4が直近3分動画
    - .jsonlが切り抜き情報
- clips/trimmed以下
    - .mp4に時間指定の切り抜き動画

## 注意点

- 開始3分以上経過しないとclipボタンは押せません
- 動画データは直近10分が保存されています
- 同じ窓枠で録画をし直すと直近5分のデータは削除されます

## その他機能

### オプション変更

- urlの末尾に以下を加えることで設定を変更できます
    - `quality={best, 1080p, 720p, 480p, 360p, 240p}`: 画質設定（デフォルトbest）
    - `duration=N`: 直近N分のクリップを作成します（デフォルト3）
    - `buffer=N`: 直近N分をバッファとして保存しておきます（デフォルト10）

- 例:
    - `http://localhost:8866/?quality=480p&duration=1&buffer=3`