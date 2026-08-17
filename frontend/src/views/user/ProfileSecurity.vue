<template>
  <div>
    <el-card class="card" header="双重验证（MFA）">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="状态">
          <el-tag :type="mfaEnabled ? 'success' : 'info'">{{ mfaEnabled ? '已启用' : '未启用' }}</el-tag>
          <span v-if="!mfaEnabled" class="force-tip">
            {{ userStore.role === 'admin' ? '（管理员角色强制启用，绑定后才能提升账号安全）' : '（建议启用，可选）' }}
          </span>
        </el-descriptions-item>
      </el-descriptions>

      <!-- 绑定流程 -->
      <div v-if="binding" class="bind-box">
        <template v-if="bindStep === 'qr'">
          <p class="step-text">1. 使用身份验证器 App（Google Authenticator / Microsoft Authenticator / 1Password 等）扫描二维码：</p>
          <img v-if="qrImage" :src="qrImage" class="qr-img" alt="MFA 二维码" />
          <div v-else class="qr-loading">二维码加载中…</div>
          <p class="secret">密钥：{{ bindSecret }}</p>
          <el-button type="primary" @click="bindStep = 'code'">我已扫描，下一步</el-button>
          <el-button @click="binding = false">取消</el-button>
        </template>
        <template v-else>
          <p class="step-text">2. 输入 App 中显示的 6 位动态验证码完成绑定：</p>
          <div class="bind-code-row">
            <el-input v-model="bindCode" maxlength="6" placeholder="6 位数字" style="width: 200px" />
            <el-button type="primary" :loading="bindConfirming" @click="confirmBind">确认绑定</el-button>
            <el-button @click="binding = false">取消</el-button>
          </div>
        </template>
      </div>

      <div v-else class="bind-actions">
        <el-button v-if="!mfaEnabled" type="primary" @click="startBind">绑定 MFA</el-button>
        <el-button v-else type="danger" plain :disabled="!canDisable" @click="disableVisible = true">
          {{ canDisable ? '解绑 MFA' : '管理员角色不可解绑' }}
        </el-button>
      </div>
    </el-card>

    <el-card class="card" header="登录会话（可在其他设备主动下线）">
      <el-table :data="sessions" size="small" v-loading="sessionLoading">
        <el-table-column prop="created_at" label="登录时间" width="180" />
        <el-table-column prop="expires_at" label="过期时间" width="180" />
        <el-table-column prop="ip_address" label="来源 IP" width="140" />
        <el-table-column prop="user_agent" label="设备" show-overflow-tooltip />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.current" type="success" size="small">当前</el-tag>
            <el-button v-else size="small" type="danger" link @click="revoke(row)">下线</el-button>
          </template>
        </el-table-column>
        <template #empty>暂无登录会话</template>
      </el-table>
    </el-card>

    <el-dialog v-model="disableVisible" title="解绑 MFA" width="360px">
      <p>请输入当前身份验证器中的 6 位动态验证码，确认解绑：</p>
      <el-input v-model="disableCode" maxlength="6" placeholder="6 位数字" />
      <template #footer>
        <el-button @click="disableVisible = false">取消</el-button>
        <el-button type="danger" :loading="disabling" @click="confirmDisable">确认解绑</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import QRCode from 'qrcode'
import { useUserStore } from '@/stores/user'
import { authApi } from '@/api/auth'

const userStore = useUserStore()

const mfaEnabled = ref(false)
const canDisable = ref(true)
const sessions = ref([])
const sessionLoading = ref(false)

const binding = ref(false)
const bindStep = ref('qr')
const bindCode = ref('')
const bindSecret = ref('')
const qrImage = ref('')
const bindConfirming = ref(false)

const disableVisible = ref(false)
const disableCode = ref('')
const disabling = ref(false)

async function loadSessions() {
  sessionLoading.value = true
  try {
    const data = await authApi.sessions()
    sessions.value = data.items || []
  } finally {
    sessionLoading.value = false
  }
}

async function startBind() {
  binding.value = true
  bindStep.value = 'qr'
  bindCode.value = ''
  const data = await authApi.mfaBind()
  bindSecret.value = data.secret
  QRCode.toDataURL(data.otpauth_url, { width: 160, margin: 1 }).then((u) => { qrImage.value = u })
}

async function confirmBind() {
  if (!bindCode.value) { ElMessage.warning('请输入验证码'); return }
  bindConfirming.value = true
  try {
    await authApi.mfaBindConfirm(bindCode.value)
    ElMessage.success('MFA 已启用')
    binding.value = false
    mfaEnabled.value = true
  } catch (e) {
    ElMessage.error(e?.message || '绑定失败')
    bindCode.value = ''
  } finally {
    bindConfirming.value = false
  }
}

async function confirmDisable() {
  if (!disableCode.value) { ElMessage.warning('请输入验证码'); return }
  disabling.value = true
  try {
    await authApi.mfaDisable(disableCode.value)
    ElMessage.success('MFA 已解绑')
    disableVisible.value = false
    disableCode.value = ''
    mfaEnabled.value = false
  } catch (e) {
    ElMessage.error(e?.message || '解绑失败')
    disableCode.value = ''
  } finally {
    disabling.value = false
  }
}

async function revoke(row) {
  await authApi.revokeSession(row.id)
  ElMessage.success('该会话已下线')
  loadSessions()
}

onMounted(() => {
  // 登录响应未暴露 MFA 状态，通过用户可解绑性 + 角色推断；此处以绑定操作结果为准
  mfaEnabled.value = false
  canDisable.value = userStore.role !== 'admin'
  loadSessions()
})
</script>

<style scoped>
.card { margin-bottom: 16px; }
.force-tip { color: #909399; font-size: 12px; margin-left: 8px; }
.bind-box { margin-top: 16px; padding: 16px; background: #f8f9fb; border-radius: 6px; }
.step-text { color: #666; margin: 0 0 12px; }
.qr-img { width: 160px; height: 160px; display: block; }
.qr-loading { width: 160px; height: 160px; line-height: 160px; color: #999; background: #fff; text-align: center; }
.secret { margin: 10px 0; font-size: 12px; color: #909399; word-break: break-all; }
.bind-actions { margin-top: 16px; }
.bind-code-row { display: flex; gap: 10px; align-items: center; }
</style>
