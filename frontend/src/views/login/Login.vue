<template>
  <div class="login-page">
    <el-card class="login-card">
      <div class="title">🛡️ 蓝队业务管理系统</div>
      <div class="subtitle">沟通协同 · 能力培养 · 资产管控 · 人员治理</div>

      <!-- 第一步：用户名密码 + 验证码 -->
      <el-form v-if="step === 'form'" label-position="top" @keyup.enter="onLogin">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="请输入用户名" clearable />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="请输入密码" show-password />
        </el-form-item>
        <el-form-item v-if="showCaptcha" label="验证码">
          <div class="captcha-row">
            <el-input v-model="form.captcha_code" placeholder="输入右侧字符" />
            <img :src="captchaImage" class="captcha-img" alt="验证码" title="点击刷新" @click="loadCaptcha" />
          </div>
        </el-form-item>
        <el-button type="primary" :loading="loading" class="submit" @click="onLogin">登 录</el-button>
      </el-form>

      <!-- 第二步：MFA 二次验证 -->
      <el-form v-else label-position="top" @keyup.enter="onMfaConfirm">
        <div class="mfa-tip">
          {{ step === 'setup' ? '请使用身份验证器 App（Google/Microsoft Authenticator 等）扫描二维码完成绑定——管理员首次登录必须绑定 MFA。' : '请输入身份验证器中的 6 位动态验证码。' }}
        </div>
        <div v-if="step === 'setup'" class="qr-wrap">
          <img v-if="qrImage" :src="qrImage" class="qr-img" alt="MFA 二维码" />
          <div v-else class="qr-loading">二维码加载中…</div>
          <div class="secret">密钥：{{ otpauth.secret }}</div>
        </div>
        <el-form-item label="动态验证码">
          <el-input v-model="mfaCode" maxlength="6" placeholder="6 位数字" />
        </el-form-item>
        <el-button type="primary" :loading="mfaLoading" class="submit" @click="onMfaConfirm">
          {{ step === 'setup' ? '绑定并登录' : '验证并登录' }}
        </el-button>
        <div v-if="step === 'mfa'" class="back-login">
          <el-link type="info" @click="resetLogin">返回重新登录</el-link>
        </div>
      </el-form>

      <div class="hint">
        管理员 admin / admin123（首次登录需绑定 MFA）<br />
        演示账号 manager01 · analyst01 · trainee01 · auditor01 / Bt@123456
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import QRCode from 'qrcode'
import { useUserStore } from '@/stores/user'
import { authApi } from '@/api/auth'

const router = useRouter()
const userStore = useUserStore()

const step = ref('form')
const loading = ref(false)
const mfaLoading = ref(false)
const showCaptcha = ref(false)
const captchaImage = ref('')
const mfaCode = ref('')
const mfaToken = ref('')
const otpauth = ref({ secret: '', otpauth_url: '' })
const qrImage = ref('')
const form = reactive({ username: 'admin', password: '', captcha_id: '', captcha_code: '' })

async function loadCaptcha() {
  const data = await authApi.captcha()
  captchaImage.value = data.image
  form.captcha_id = data.captcha_id
}

function resetLogin() {
  step.value = 'form'
  mfaCode.value = ''
  mfaToken.value = ''
  qrImage.value = ''
}

async function onLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  if (showCaptcha.value && (!form.captcha_id || !form.captcha_code)) {
    ElMessage.warning('请填写验证码')
    return
  }
  loading.value = true
  try {
    const data = await userStore.login(form.username, form.password, {
      captcha_id: form.captcha_id,
      captcha_code: form.captcha_code
    })
    if (data.mfa_required) {
      mfaToken.value = data.mfa_token || ''
      step.value = data.mfa_setup ? 'setup' : 'mfa'
      if (data.mfa_setup) {
        const setup = await authApi.mfaSetup(data.mfa_token)
        otpauth.value = setup
        QRCode.toDataURL(setup.otpauth_url, { width: 180, margin: 1 }).then((u) => { qrImage.value = u })
      }
      return
    }
    ElMessage.success(`欢迎，${data.user.real_name || data.user.username}`)
    router.push(`/dashboard/${data.user.role}`)
  } catch (e) {
    ElMessage.error(e?.message || '登录失败')
    // 连续失败达到阈值后需验证码：统一刷新展示
    showCaptcha.value = true
    form.captcha_code = ''
    loadCaptcha().catch(() => {})
  } finally {
    loading.value = false
  }
}

async function onMfaConfirm() {
  if (!mfaCode.value) {
    ElMessage.warning('请输入动态验证码')
    return
  }
  mfaLoading.value = true
  try {
    const data = step.value === 'setup'
      ? await authApi.mfaConfirm(mfaToken.value, mfaCode.value)
      : await authApi.mfaVerify(mfaToken.value, mfaCode.value)
    userStore.setUser(data.user)
    ElMessage.success(`欢迎，${data.user.real_name || data.user.username}`)
    router.push(`/dashboard/${data.user.role}`)
  } catch (e) {
    ElMessage.error(e?.message || '验证失败')
    mfaCode.value = ''
  } finally {
    mfaLoading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f2027, #203a43, #2c5364);
}
.login-card { width: 380px; }
.title { font-size: 20px; font-weight: 700; text-align: center; }
.subtitle { text-align: center; color: #999; margin: 6px 0 20px; font-size: 12px; }
.submit { width: 100%; }
.hint { margin-top: 14px; font-size: 12px; color: #999; text-align: center; line-height: 1.8; }
.captcha-row { display: flex; gap: 10px; width: 100%; }
.captcha-img { height: 34px; width: 110px; cursor: pointer; border: 1px solid #dcdfe6; border-radius: 4px; }
.mfa-tip { font-size: 13px; color: #666; line-height: 1.7; margin-bottom: 14px; }
.qr-wrap { text-align: center; margin-bottom: 14px; }
.qr-img { width: 180px; height: 180px; }
.qr-loading { height: 180px; line-height: 180px; color: #999; }
.secret { margin-top: 8px; font-size: 12px; color: #909399; word-break: break-all; }
.back-login { margin-top: 10px; text-align: center; }
</style>
