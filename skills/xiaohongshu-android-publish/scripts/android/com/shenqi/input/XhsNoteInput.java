package com.shenqi.input;

import android.os.Bundle;
import java.lang.reflect.Method;
import java.security.MessageDigest;

/**
 * Legacy UiAutomator fill-only test. It never presses a publish/submit button.
 * The caller owns the live worker, unlocked-device and account-identity guards.
 * QueryController reflection preserves the mechanism in the captured source;
 * it is an implementation dependency, not a stable public Android SDK API.
 */
public class XhsNoteInput extends com.android.uiautomator.testrunner.UiAutomatorTestCase {
    private static final String PACKAGE = "com.xingin.xhs";
    private static final String EDIT_TEXT = "android.widget.EditText";
    private static final int ACTION_SET_TEXT = 0x200000;
    private static final String ARG_SET_TEXT = "ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE";
    private String stage = "validate_params";

    private static Method m(Class<?> c, String name, Class<?>... params) throws Exception {
        try {
            return c.getMethod(name, params);
        } catch (NoSuchMethodException e) {
            Method method = c.getDeclaredMethod(name, params);
            method.setAccessible(true);
            return method;
        }
    }

    private static void require(boolean condition, String code) {
        if (!condition) throw new AssertionError(code);
    }

    private static String param(Bundle params, String name) {
        require(params != null, "PARAMS_MISSING");
        Object value = params.get(name);
        require(value instanceof String, "PARAM_MISSING_OR_NOT_STRING");
        String text = (String) value;
        require(text.trim().length() > 0 && text.indexOf('\u0000') < 0, "PARAM_EMPTY_OR_NUL");
        return text;
    }

    private static String sha256(String text) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(text.getBytes("UTF-8"));
        StringBuilder out = new StringBuilder();
        for (byte value : digest) {
            int n = value & 255;
            if (n < 16) out.append('0');
            out.append(Integer.toHexString(n));
        }
        return out.toString();
    }

    private static void foreground(Object device) throws Exception {
        Object current = m(device.getClass(), "getCurrentPackageName").invoke(device);
        require(PACKAGE.equals(current), "FOREGROUND_PACKAGE_MISMATCH");
    }

    private static void validateNode(Object node, Class<?> ani) throws Exception {
        require(node != null && ani.isInstance(node), "NODE_MISSING");
        Object pkg = ani.getMethod("getPackageName").invoke(node);
        Object cls = ani.getMethod("getClassName").invoke(node);
        require(pkg != null && PACKAGE.contentEquals((CharSequence) pkg), "NODE_PACKAGE_MISMATCH");
        require(cls != null && EDIT_TEXT.contentEquals((CharSequence) cls), "NODE_CLASS_MISMATCH");
        require(Boolean.TRUE.equals(ani.getMethod("isEnabled").invoke(node)), "NODE_DISABLED");
        require(Boolean.TRUE.equals(ani.getMethod("isEditable").invoke(node)), "NODE_NOT_EDITABLE");
        require(Boolean.FALSE.equals(ani.getMethod("isPassword").invoke(node)), "PASSWORD_FIELD_REJECTED");
    }

    private static final class Field {
        final Object selector;
        final Object object;
        Object node;

        Field(Class<?> selectorClass, Class<?> objectClass, String placeholder) throws Exception {
            Object sel = selectorClass.getConstructor().newInstance();
            sel = m(selectorClass, "packageName", String.class).invoke(sel, PACKAGE);
            sel = m(selectorClass, "className", String.class).invoke(sel, EDIT_TEXT);
            selector = m(selectorClass, "text", String.class).invoke(sel, placeholder);
            object = objectClass.getConstructor(selectorClass).newInstance(selector);
        }

        void locate(Class<?> selectorClass, Class<?> objectClass, Class<?> ani) throws Exception {
            require(Boolean.TRUE.equals(m(objectClass, "exists").invoke(object)), "FIELD_NOT_FOUND");
            Object controller = m(objectClass, "getQueryController").invoke(object);
            node = m(controller.getClass(), "findAccessibilityNodeInfo", selectorClass).invoke(controller, selector);
            validateNode(node, ani);
        }
    }

    private void fill(Field field, String text, Object device, Class<?> selectorClass,
                      Class<?> objectClass, Class<?> ani) throws Exception {
        foreground(device);
        require(Boolean.TRUE.equals(m(objectClass, "click").invoke(field.object)), "FIELD_CLICK_FAILED");
        m(device.getClass(), "waitForIdle").invoke(device);
        foreground(device);
        field.locate(selectorClass, objectClass, ani);
        Bundle arguments = new Bundle();
        arguments.putCharSequence(ARG_SET_TEXT, text);
        Object result = ani.getMethod("performAction", int.class, Bundle.class)
                .invoke(field.node, ACTION_SET_TEXT, arguments);
        require(Boolean.TRUE.equals(result), "ACTION_SET_TEXT_FALSE");
        readExact(field, text, device, ani);
    }

    private String readExact(Field field, String expected, Object device, Class<?> ani) throws Exception {
        // Refresh the actual UI node; never compare against only the input Bundle.
        for (int attempt = 0; attempt < 10; attempt++) {
            foreground(device);
            boolean refreshed = Boolean.TRUE.equals(ani.getMethod("refresh").invoke(field.node));
            if (refreshed) {
                validateNode(field.node, ani);
                Object raw = ani.getMethod("getText").invoke(field.node);
                if (raw instanceof CharSequence && expected.equals(raw.toString())) return raw.toString();
            }
            Thread.sleep(100);
        }
        throw new AssertionError("FULL_TEXT_READBACK_MISMATCH_OR_STALE_NODE");
    }

    public void testFillTitleAndBody() throws Exception {
        try {
            Bundle params = getParams();
            String postId = param(params, "post_id");
            String title = param(params, "title");
            String body = param(params, "body");
            String titlePin = param(params, "title_sha256");
            String bodyPin = param(params, "body_sha256");
            require(postId.matches("[A-Za-z0-9][A-Za-z0-9._-]{0,79}"), "POST_ID_INVALID");
            require(titlePin.matches("[0-9a-f]{64}") && bodyPin.matches("[0-9a-f]{64}"), "HASH_PIN_INVALID");
            require(titlePin.equals(sha256(title)) && bodyPin.equals(sha256(body)), "PARAMETER_HASH_MISMATCH");

            stage = "locate_fields";
            Object device = getClass().getMethod("getUiDevice").invoke(this);
            Class<?> selectorClass = Class.forName("com.android.uiautomator.core.UiSelector");
            Class<?> objectClass = Class.forName("com.android.uiautomator.core.UiObject");
            Class<?> ani = Class.forName("android.view.accessibility.AccessibilityNodeInfo");
            m(device.getClass(), "waitForIdle").invoke(device);
            foreground(device);
            Field titleField = new Field(selectorClass, objectClass, "\u6dfb\u52a0\u6807\u9898");
            Field bodyField = new Field(selectorClass, objectClass, "\u6dfb\u52a0\u6b63\u6587");
            // Verify both expected editable fields before modifying either one.
            titleField.locate(selectorClass, objectClass, ani);
            bodyField.locate(selectorClass, objectClass, ani);

            stage = "fill_title";
            fill(titleField, title, device, selectorClass, objectClass, ani);
            stage = "fill_body";
            fill(bodyField, body, device, selectorClass, objectClass, ani);
            stage = "final_full_readback";
            String actualTitle = readExact(titleField, title, device, ani);
            String actualBody = readExact(bodyField, body, device, ani);
            foreground(device);
            System.out.println("SHENQI_INPUT_RESULT {\"status\":\"filled_and_verified\",\"post_id\":\"" + postId
                    + "\",\"title_readback_sha256\":\"" + sha256(actualTitle)
                    + "\",\"body_readback_sha256\":\"" + sha256(actualBody)
                    + "\",\"title_utf16_length\":" + actualTitle.length()
                    + ",\"body_utf16_length\":" + actualBody.length()
                    + ",\"title_readback_matches\":true,\"body_readback_matches\":true,\"publication_clicked\":false}");
        } catch (Throwable error) {
            // Class and fixed stage only; no caption, parameter values or exception message.
            System.out.println("SHENQI_INPUT_RESULT {\"status\":\"failed\",\"stage\":\"" + stage
                    + "\",\"error_class\":\"" + error.getClass().getSimpleName()
                    + "\",\"publication_clicked\":false}");
            throw new AssertionError("FILL_NOT_VERIFIED:" + stage);
        }
    }
}
