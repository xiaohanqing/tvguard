#!/bin/bash
# TVGuard 提示页 APK 构建脚本（纯命令行，不依赖 gradle）
# 用法: ./build.sh   产物: tvguard-blocker.apk
set -e
cd "$(dirname "$0")"

SDK="${ANDROID_SDK:-/d/Users/chunxiao.li/AppData/Local/Android/Sdk}"
BT="$SDK/build-tools/36.0.0"
PLATFORM="$SDK/platforms/android-35/android.jar"
KEYSTORE="tvguard.keystore"
OUT="tvguard-blocker.apk"
# d8 需要 Java 11+，系统 JDK 8 不够，用 Android Studio 内置 JBR
JBR="/d/soft/android_studio/jbr/bin"

# 自签名密钥（首次生成，之后复用）
if [ ! -f "$KEYSTORE" ]; then
  keytool -genkeypair -keystore "$KEYSTORE" -alias tvguard \
    -keyalg RSA -keysize 2048 -validity 10950 \
    -storepass tvguard123 -keypass tvguard123 \
    -dname "CN=TVGuard, OU=Home, O=TVGuard" 2>/dev/null
fi

rm -rf build && mkdir -p build/gen build/obj build/dex

echo "==> aapt2 编译资源..."
"$BT/aapt2.exe" compile --dir res -o build/res.zip

echo "==> aapt2 链接..."
"$BT/aapt2.exe" link -o build/app.unaligned.apk \
  -I "$PLATFORM" --manifest AndroidManifest.xml \
  --min-sdk-version 21 --target-sdk-version 35 \
  --java build/gen build/res.zip

echo "==> javac 编译..."
javac -encoding UTF-8 \
  -bootclasspath "$PLATFORM" \
  -classpath "$PLATFORM" \
  -d build/obj build/gen/com/tvguard/blocker/R.java java/com/tvguard/blocker/BlockerActivity.java

echo "==> d8 转 dex..."
"$JBR/java.exe" -cp "$BT/lib/d8.jar" com.android.tools.r8.D8 --release \
  --lib "$PLATFORM" --min-api 21 \
  --output build/dex $(find build/obj -name "*.class")

echo "==> 打包 dex..."
cd build && cp app.unaligned.apk app.apk && cd ..
python -c "
import zipfile, shutil
shutil.move('build/app.apk', 'build/app.nodex.apk')
with zipfile.ZipFile('build/app.nodex.apk') as zin, zipfile.ZipFile('build/app.apk', 'w', zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        zout.writestr(item, zin.read(item.filename))
    zout.write('build/dex/classes.dex', 'classes.dex')
"

echo "==> zipalign 对齐..."
"$BT/zipalign.exe" -f 4 build/app.apk "$OUT"

echo "==> 签名..."
"$BT/apksigner.bat" sign --ks "$KEYSTORE" \
  --ks-pass pass:tvguard123 --key-pass pass:tvguard123 \
  --out "$OUT" "$OUT"

"$BT/apksigner.bat" verify "$OUT" && echo "==> 完成: $OUT"
