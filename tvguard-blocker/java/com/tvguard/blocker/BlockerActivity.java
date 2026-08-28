package com.tvguard.blocker;

import android.app.Activity;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * TVGuard 拦截提示页：全屏展示「为什么被拦截」。
 *
 * 由服务端通过 adb 拉起并传参：
 *   am start -n com.tvguard.blocker/.BlockerActivity
 *      --es app "飞牛播放器" --es reason "不在允许时间段内" --es extra "..."
 *
 * 后续互动内容（答题解锁等）在 onInteraction 里扩展。
 */
public class BlockerActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // 常亮 + 全屏
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN,
                WindowManager.LayoutParams.FLAG_FULLSCREEN);

        String app = opt("app", "");
        String reason = opt("reason", "");
        String extra = opt("extra", "");

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setBackgroundColor(Color.parseColor("#10141C"));
        int pad = dp(48);
        root.setPadding(pad, pad, pad, pad);

        ClockIcon icon = new ClockIcon(this);
        LinearLayout.LayoutParams iconLp =
                new LinearLayout.LayoutParams(dp(72), dp(72));
        TextView title = text(app + " 先休息一下吧", dp(36), Color.WHITE);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setPadding(0, dp(24), 0, 0);

        TextView msg = text(reason.isEmpty() ? "今天的观看时间结束啦，明天再见"
                : reason, dp(24), Color.parseColor("#8A94A8"));
        msg.setPadding(0, dp(16), 0, 0);

        root.addView(icon, iconLp);
        root.addView(title);
        root.addView(msg);

        // 预留：附加互动内容区域（extra 非空时展示，后续扩展为答题/任务等）
        if (!extra.isEmpty()) {
            TextView extraView = text(extra, dp(20), Color.parseColor("#4F8CFF"));
            extraView.setPadding(0, dp(32), 0, 0);
            root.addView(extraView);
        }

        setContentView(root);
    }

    /** 互动扩展点：遥控器按键回调，后续答题解锁在这里实现。 */
    @Override
    public boolean onKeyDown(int keyCode, android.view.KeyEvent event) {
        // 目前任意按键关闭提示页回到桌面
        finish();
        return super.onKeyDown(keyCode, event);
    }

    /** 复用实例时刷新文案（am start 带 CLEAR_TOP 时旧实例重建，此处兜底）。 */
    @Override
    protected void onNewIntent(android.content.Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        recreate();
    }

    private String opt(String key, String def) {
        String v = getIntent() == null ? null : getIntent().getStringExtra(key);
        return v == null ? def : v;
    }

    private TextView text(String s, int sizePx, int color) {
        TextView tv = new TextView(this);
        tv.setText(s);
        tv.setTextSize(sizePx / getDensity());
        tv.setTextColor(color);
        tv.setGravity(Gravity.CENTER);
        tv.setLineSpacing(dp(6), 1.1f);
        return tv;
    }

    private float getDensity() {
        return getResources().getDisplayMetrics().density;
    }

    private int dp(int v) {
        return Math.round(v * getDensity());
    }

    private int dp(float v) {
        return Math.round(v * getDensity());
    }

    /** 时钟图标：矢量绘制（替代 Emoji，任意分辨率清晰）。 */
    private class ClockIcon extends android.view.View {
        ClockIcon(Context ctx) { super(ctx); }

        @Override
        protected void onDraw(android.graphics.Canvas c) {
            int w = getWidth(), h = getHeight();
            float cx = w / 2f, cy = h / 2f;
            float r = Math.min(w, h) / 2f - dp(3);

            android.graphics.Paint p = new android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG);

            // 圆环
            p.setStyle(android.graphics.Paint.Style.STROKE);
            p.setStrokeWidth(dp(4));
            p.setShader(new android.graphics.LinearGradient(cx - r, cy - r, cx + r, cy + r,
                    0xFF6FA8FF, 0xFF3D6FD6, android.graphics.Shader.TileMode.CLAMP));
            c.drawCircle(cx, cy, r - dp(2), p);

            // 指针（~10:10）
            p.setShader(null);
            p.setColor(0xFFD7E4FA);
            p.setStrokeCap(android.graphics.Paint.Cap.ROUND);
            p.setStrokeWidth(dp(3.5f));
            double hAng = Math.toRadians(-60 - 90), mAng = Math.toRadians(50 - 90);
            float hr = r * 0.42f, mr = r * 0.62f;
            c.drawLine(cx, cy, cx + (float) (hr * Math.cos(hAng)), cy + (float) (hr * Math.sin(hAng)), p);
            p.setStrokeWidth(dp(2.5f));
            c.drawLine(cx, cy, cx + (float) (mr * Math.cos(mAng)), cy + (float) (mr * Math.sin(mAng)), p);

            // 中心点
            p.setStyle(android.graphics.Paint.Style.FILL);
            p.setColor(0xFF6FA8FF);
            c.drawCircle(cx, cy, dp(3.5f), p);
        }
    }
}
