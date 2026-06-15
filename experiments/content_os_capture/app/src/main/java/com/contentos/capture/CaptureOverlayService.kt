package com.contentos.capture

import android.app.Service
import android.content.Intent
import android.graphics.PixelFormat
import android.os.IBinder
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.TextView

class CaptureOverlayService : Service() {
    private var windowManager: WindowManager? = null
    private var overlay: View? = null

    override fun onCreate() {
        super.onCreate()
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        showOverlay()
    }

    override fun onDestroy() {
        overlay?.let { windowManager?.removeView(it) }
        overlay = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun showOverlay() {
        if (overlay != null) return
        val button = TextView(this).apply {
            text = "收"
            textSize = 16f
            gravity = Gravity.CENTER
            setTextColor(0xFFFFFFFF.toInt())
            setBackgroundColor(0xFF2563EB.toInt())
            setOnClickListener {
                text = "✓"
                announceForAccessibility("已收进灵感箱")
            }
            setOnLongClickListener {
                stopSelf()
                true
            }
        }
        val params = WindowManager.LayoutParams(
            128,
            128,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            x = 24
            y = 260
        }
        makeDraggable(button, params)
        windowManager?.addView(button, params)
        overlay = button
    }

    private fun makeDraggable(view: View, params: WindowManager.LayoutParams) {
        var startX = 0
        var startY = 0
        var downRawX = 0f
        var downRawY = 0f
        view.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    startX = params.x
                    startY = params.y
                    downRawX = event.rawX
                    downRawY = event.rawY
                    false
                }
                MotionEvent.ACTION_MOVE -> {
                    params.x = startX - (event.rawX - downRawX).toInt()
                    params.y = startY + (event.rawY - downRawY).toInt()
                    windowManager?.updateViewLayout(view, params)
                    true
                }
                else -> false
            }
        }
    }
}
