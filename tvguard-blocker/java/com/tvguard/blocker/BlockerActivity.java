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

        TextView emoji = text("⏰", dp(72), Color.WHITE);
        TextView title = text(app + " 先休息一下吧", dp(36), Color.WHITE);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setPadding(0, dp(24), 0, 0);

        TextView msg = text(reason.isEmpty() ? "今天的观看时间结束啦，明天再见"
                : reason + "，明天再来哦", dp(24), Color.parseColor("#8A94A8"));
        msg.setPadding(0, dp(16), 0, 0);

        root.addView(emoji);
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
}
