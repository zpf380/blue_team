<template>
  <div class="page">
    <el-card v-loading="subnetLoading">
      <div class="head">
        <div>
          <h3>🌐 IP 地址管理</h3>
          <p class="sub">管理子网规划与地址分配；网关可自动推导，地址可手动指定或自动从子网获取首个空闲 IP，支持保留段、VLSM 划分子网与使用率热图。</p>
        </div>
        <div class="ops">
          <el-button type="primary" plain v-permission="'ipam:manage'" @click="openVlsm">VLSM 划分子网</el-button>
          <el-button type="primary" v-permission="'ipam:manage'" @click="openSubnet()">新增子网</el-button>
        </div>
      </div>

      <el-empty v-if="!subnets.length && !subnetLoading" description="暂无子网，点击「新增子网」登记网段规划" />
      <el-table v-else :data="subnets" stripe>
        <el-table-column prop="name" label="子网名称" min-width="120" />
        <el-table-column prop="network" label="网段" min-width="120" />
        <el-table-column prop="gateway" label="网关" width="120" />
        <el-table-column prop="vlan_id" label="VLAN" width="70">
          <template #default="{ row }">{{ row.vlan_id ?? '—' }}</template>
        </el-table-column>
        <el-table-column prop="department_name" label="部门" width="100" />
        <el-table-column label="保留段" min-width="110">
          <template #default="{ row }">
            <el-tag v-for="r in (row.reserved_ranges || [])" :key="r" size="small" type="warning" class="res-tag">{{ r }}</el-tag>
            <span v-if="!(row.reserved_ranges || []).length" class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="地址用量" min-width="170">
          <template #default="{ row }">
            <el-progress
              :percentage="pct(row)" :stroke-width="8"
              :color="row.capacity ? (row.used / row.capacity > 0.8 ? '#f56c6c' : '#67c23a') : '#c0c4cc'"
            />
            <span class="muted">{{ row.used }} / {{ row.capacity }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openUsage(row)">热图</el-button>
            <el-button v-permission="'ipam:manage'" link type="primary" @click="openEditSubnet(row)">编辑</el-button>
            <el-button v-permission="'ipam:manage'" link type="danger" @click="openDeleteSubnet(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="alloc-card" v-loading="allocLoading">
      <div class="head">
        <h3 class="alloc-title">地址分配记录</h3>
        <div class="ops">
          <el-input v-model="allocQuery.keyword" placeholder="IP / 用途" clearable style="width: 200px" @keyup.enter="loadAlloc" @clear="loadAlloc" />
          <el-select v-model="allocQuery.subnet_id" placeholder="子网" clearable style="width: 160px" @change="loadAlloc">
            <el-option v-for="s in subnets" :key="s.id" :label="s.network" :value="s.id" />
          </el-select>
          <el-button type="primary" plain @click="loadAlloc">查询</el-button>
          <el-button type="primary" v-permission="'ipam:manage'" @click="openAlloc()">分配地址</el-button>
          <el-button v-permission="'ipam:manage'" :loading="recycling" @click="recycleLeases">回收过期租约</el-button>
        </div>
      </div>

      <el-empty v-if="!allocs.length && !allocLoading" description="暂无地址分配，点击「分配地址」登记 IP 用途" />
      <el-table v-else :data="allocs" stripe>
        <el-table-column prop="ip_address" label="IP 地址" min-width="125" />
        <el-table-column prop="subnet_name" label="所属子网" min-width="130" />
        <el-table-column label="类型" width="85">
          <template #default="{ row }">
            <el-tag size="small" :type="allocTag(row.allocation_type)">{{ allocText(row.allocation_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="purpose" label="用途" min-width="130" show-overflow-tooltip />
        <el-table-column prop="allocated_to_name" label="使用人" width="95">
          <template #default="{ row }">{{ row.allocated_to_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="device_name" label="关联设备" width="105">
          <template #default="{ row }">{{ row.device_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="到期时间" width="150">
          <template #default="{ row }">
            <span class="muted">{{ row.expires_at ? fmt(row.expires_at) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openHistory(row)">历史</el-button>
            <el-button v-permission="'ipam:manage'" link type="primary" @click="openEditAlloc(row)">编辑</el-button>
            <el-button v-permission="'ipam:manage'" link type="danger" @click="release(row)">释放</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        class="pager" background layout="total, prev, pager, next" :total="allocTotal"
        :page-size="allocQuery.size" v-model:current-page="allocQuery.page" @current-change="loadAlloc"
      />
    </el-card>

    <el-card class="disc-card">
      <div class="head">
        <div>
          <h3>🔎 网络发现</h3>
          <p class="sub">输入目标网段扫描本网段终端，比对台账找出「在线未登记」的幽灵设备；勾选确认后按 IP+MAC+掩码登记为终端设备与 DHCP 分配，收敛资产台账。</p>
        </div>
        <div class="ops">
          <el-select v-model="discPickSubnet" placeholder="从已登记子网快捷选择" clearable filterable style="width: 240px" @change="onPickSubnet">
            <el-option v-for="s in subnets" :key="s.id" :label="`${s.name}（${s.network}）`" :value="s.id" />
          </el-select>
          <el-input v-model="discQuery.network" placeholder="目标网段 CIDR，如 192.168.1.0/24" clearable
            style="width: 250px" @input="discPickSubnet = null" />
          <el-button type="warning" plain v-permission="'ipam:manage'" :loading="discovering"
            :disabled="!discQuery.network" @click="startDiscovery">开始发现</el-button>
          <el-button :icon="'Refresh'" @click="loadDiscoveries">刷新</el-button>
        </div>
      </div>

      <div v-if="discResult" class="disc-result">
        <div class="disc-result-head">
          <span class="disc-subnet">{{ discResult.network }} · 掩码 {{ discResult.netmask }}</span>
          <el-tag size="small" :type="discStatusTag(discResult.scan_status)">{{ discStatusText(discResult.scan_status) }}</el-tag>
          <span v-if="discResult.subnet_name" class="muted">关联子网：{{ discResult.subnet_name }}</span>
          <el-alert v-if="discResult.scan_status === 'failed'" class="disc-err" type="error" :closable="false" :title="discResult.error || '发现失败'" />
        </div>

        <div v-if="discResult.unregistered_ips.length" class="disc-group">
          <div class="disc-group-head">
            <el-tag size="small" type="danger">幽灵设备</el-tag>
            <span class="muted">{{ discResult.unregistered_ips.length }} 台在线但未登记</span>
            <el-button v-permission="'ipam:manage'" link type="primary" size="small" @click="registerGhosts">登记所选（{{ discChecked.length }}）</el-button>
            <el-button link size="small" @click="toggleAllGhosts">全选/取消</el-button>
          </div>
          <div class="disc-ips">
            <el-checkbox v-for="ip in discResult.unregistered_ips" :key="ip" :value="ip" v-model="discChecked" class="disc-ip ghost-ip">
              {{ ip }}<span v-if="discMeta(ip).mac" class="disc-mac muted"> · {{ discMeta(ip).mac }}<template v-if="discMeta(ip).vendor">（{{ discMeta(ip).vendor }}）</template></span>
            </el-checkbox>
          </div>
        </div>

        <div v-if="discResult.registered_ips.length" class="disc-group">
          <div class="disc-group-head">
            <el-tag size="small" type="success">在线已登记</el-tag>
            <span class="muted">{{ discResult.registered_ips.length }} 台</span>
          </div>
          <div class="disc-ips">
            <el-tag v-for="ip in discResult.registered_ips" :key="ip" size="small" type="success" class="disc-ip">{{ ip }}<span v-if="discMeta(ip).mac" class="disc-mac"> · {{ discMeta(ip).mac }}</span></el-tag>
          </div>
        </div>

        <div v-if="discResult.offline_ips.length" class="disc-group">
          <div class="disc-group-head">
            <el-tag size="small" type="info">台账在册但未在线</el-tag>
            <span class="muted">{{ discResult.offline_ips.length }} 台（可能下线/未响应，仅提示）</span>
          </div>
          <div class="disc-ips">
            <el-tag v-for="ip in discResult.offline_ips" :key="ip" size="small" type="info" class="disc-ip">{{ ip }}</el-tag>
          </div>
        </div>
      </div>
      <el-empty v-else-if="!discList.length" description="输入目标网段（或从已登记子网快捷选择）后点击「开始发现」，扫描在线终端并按 IP+MAC+掩码登记" :image-size="60" />

      <el-table v-if="discList.length" :data="discList" stripe class="disc-history">
        <el-table-column label="来源" min-width="130"><template #default="{ row }">{{ row.subnet_name || '手动网段' }}</template></el-table-column>
        <el-table-column prop="network" label="网段" min-width="120" />
        <el-table-column label="在线" width="65"><template #default="{ row }">{{ row.online_count }}</template></el-table-column>
        <el-table-column label="幽灵" width="65">
          <template #default="{ row }"><span :class="{ 'ghost-num': row.unregistered_count }">{{ row.unregistered_count }}</span></template>
        </el-table-column>
        <el-table-column label="已登记" width="75"><template #default="{ row }">{{ row.registered_count }}</template></el-table-column>
        <el-table-column label="离线" width="65"><template #default="{ row }">{{ row.offline_count }}</template></el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }"><el-tag size="small" :type="discStatusTag(row.scan_status)">{{ discStatusText(row.scan_status) }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="created_by_name" label="发起人" width="90">
          <template #default="{ row }">{{ row.created_by_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="时间" width="170"><template #default="{ row }">{{ fmt(row.created_at) }}</template></el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }"><el-button link type="primary" size="small" @click="viewDiscovery(row)">查看</el-button></template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="discList.length" class="pager" background layout="total, prev, pager, next" :total="discTotal"
        :page-size="discQuery.size" v-model:current-page="discQuery.page" @current-change="loadDiscoveries"
      />
    </el-card>

    <el-dialog v-model="subnetVisible" title="新增子网" width="480px">
      <el-form ref="subnetFormRef" :model="subnetForm" :rules="subnetRules" label-width="80px">
        <el-form-item label="子网名称" prop="name"><el-input v-model="subnetForm.name" /></el-form-item>
        <el-form-item label="网段" prop="network"><el-input v-model="subnetForm.network" placeholder="如 10.0.30.0/24" /></el-form-item>
        <el-form-item label="所属部门">
          <el-select v-model="subnetForm.department_id" clearable style="width: 100%">
            <el-option v-for="d in flatDepts" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="保留地址段">
          <el-input v-model="subnetForm.reserved_ranges_text" type="textarea" :rows="2"
            placeholder="每行一个 CIDR，如：&#10;10.0.30.100/28&#10;10.0.30.200/30" />
        </el-form-item>
        <el-alert class="auto-tip" type="info" :closable="false"
          title="网关将自动取子网第一个可用地址（如 10.0.30.1）；保留段内的地址自动分配时会跳过。"
        />
      </el-form>
      <template #footer>
        <el-button @click="subnetVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingSubnet" @click="saveSubnet">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="subnetEditVisible" title="编辑子网" width="480px" :close-on-click-modal="false">
      <el-form label-width="80px">
        <el-form-item label="子网名称"><el-input v-model="subnetEditForm.name" /></el-form-item>
        <el-form-item label="网段">
          <el-input :model-value="subnetEditTarget?.network" disabled />
        </el-form-item>
        <el-form-item label="网关"><el-input v-model="subnetEditForm.gateway" placeholder="留空不修改" /></el-form-item>
        <el-form-item label="VLAN"><el-input-number v-model="subnetEditForm.vlan_id" :min="1" :max="4094" controls-position="right" style="width: 100%" /></el-form-item>
        <el-form-item label="所属部门">
          <el-select v-model="subnetEditForm.department_id" clearable style="width: 100%">
            <el-option v-for="d in flatDepts" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="保留地址段">
          <el-input v-model="subnetEditForm.reserved_ranges_text" type="textarea" :rows="3"
            placeholder="每行一个 CIDR；留空表示清空全部保留段" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="subnetEditVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingSubnetEdit" @click="saveEditSubnet">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="subnetDelVisible" title="删除子网" width="480px" :close-on-click-modal="false">
      <div v-if="subnetDelTarget" class="del-box">
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item label="子网名称">{{ subnetDelTarget.name }}</el-descriptions-item>
          <el-descriptions-item label="网段">{{ subnetDelTarget.network }}</el-descriptions-item>
          <el-descriptions-item label="网关">{{ subnetDelTarget.gateway || '—' }}</el-descriptions-item>
          <el-descriptions-item label="地址用量">{{ subnetDelTarget.used }} / {{ subnetDelTarget.capacity }}</el-descriptions-item>
        </el-descriptions>
        <el-alert class="del-alert" type="warning" :closable="false"
          title="子网下仍有地址分配时将无法删除；删除后该网段不可再分配，历史记录保留。"
        />
        <el-form label-position="top">
          <el-form-item label="删除原因（审计留痕，可选）">
            <el-input v-model="subnetDelReason" type="textarea" :rows="3" maxlength="200" show-word-limit
              placeholder="如：网段规划调整 / 子网合并 / 误登记…"
            />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="subnetDelVisible = false">取消</el-button>
        <el-button type="danger" :loading="subnetRemoving" @click="removeSubnet">确认删除</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="allocVisible" title="分配地址" width="480px">
      <el-form ref="allocFormRef" :model="allocForm" :rules="allocRules" label-width="90px">
        <el-form-item label="所属子网" prop="subnet_id">
          <el-select v-model="allocForm.subnet_id" style="width: 100%" placeholder="选择子网">
            <el-option v-for="s in subnets" :key="s.id" :label="`${s.name}（${s.network}）`" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="IP 地址" prop="ip_address">
          <el-input v-model="allocForm.ip_address" placeholder="留空自动分配" />
        </el-form-item>
        <el-form-item label="分配类型">
          <el-select v-model="allocForm.allocation_type" style="width: 100%">
            <el-option label="静态分配" value="static" />
            <el-option label="DHCP" value="dhcp" />
            <el-option label="保留" value="reserved" />
          </el-select>
        </el-form-item>
        <el-form-item label="用途"><el-input v-model="allocForm.purpose" /></el-form-item>
        <el-form-item label="使用人">
          <el-select v-model="allocForm.allocated_to" clearable filterable style="width: 100%">
            <el-option v-for="u in users" :key="u.id" :label="u.real_name || u.username" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联设备">
          <el-select v-model="allocForm.device_id" clearable filterable style="width: 100%">
            <el-option v-for="d in devices" :key="d.id" :label="`${d.name}（${d.ip_address}）`" :value="d.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="allocVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingAlloc" @click="saveAlloc">分配</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="allocEditVisible" title="编辑分配" width="480px" :close-on-click-modal="false">
      <div v-if="allocEditTarget" class="del-box">
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item label="IP 地址">{{ allocEditTarget.ip_address }}</el-descriptions-item>
          <el-descriptions-item label="所属子网">{{ allocEditTarget.subnet_name }}</el-descriptions-item>
        </el-descriptions>
        <el-form label-width="80px">
          <el-form-item label="分配类型">
            <el-select v-model="allocEditForm.allocation_type" style="width: 100%">
              <el-option label="静态分配" value="static" />
              <el-option label="DHCP" value="dhcp" />
              <el-option label="保留" value="reserved" />
            </el-select>
          </el-form-item>
          <el-form-item label="用途"><el-input v-model="allocEditForm.purpose" /></el-form-item>
          <el-form-item label="使用人">
            <el-select v-model="allocEditForm.allocated_to" clearable filterable style="width: 100%">
              <el-option v-for="u in users" :key="u.id" :label="u.real_name || u.username" :value="u.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="关联设备">
            <el-select v-model="allocEditForm.device_id" clearable filterable style="width: 100%">
              <el-option v-for="d in devices" :key="d.id" :label="`${d.name}（${d.ip_address}）`" :value="d.id" />
            </el-select>
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="allocEditVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingAllocEdit" @click="saveEditAlloc">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="historyVisible" title="IP 地址轨迹" width="620px" :close-on-click-modal="false">
      <div v-if="historyIp" class="hist-title">IP：{{ historyIp }}</div>
      <el-timeline v-loading="historyLoading">
        <el-timeline-item v-for="h in historyList" :key="h.id" :timestamp="fmt(h.created_at)">
          <div class="hist-item">
            <el-tag size="small" :type="histTag(h.action)">{{ histText(h.action) }}</el-tag>
            <span class="hist-op">{{ h.username || '系统' }}（{{ h.role_code || '—' }}）</span>
            <div v-if="h.detail" class="hist-detail">{{ fmtDetail(h) }}</div>
          </div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!historyLoading && !historyList.length" description="暂无该 IP 的审计记录" />
    </el-dialog>

    <el-dialog v-model="usageVisible" title="网段使用率热图" width="880px" :close-on-click-modal="false">
      <div v-if="usageData" class="usage-head">
        <span class="usage-name">{{ usageData.name }}（{{ usageData.network }}）</span>
        <span class="usage-meta">网关 {{ usageData.gateway || '—' }} · 已用 {{ usageData.used }} / {{ usageData.capacity }} · {{ usageData.vlan_id ? 'VLAN ' + usageData.vlan_id : '' }}</span>
      </div>
      <div v-if="usageCells.length" class="heatmap">
        <div v-for="cell in usageCells" :key="cell.ip" class="cell" :style="{ background: cell.color }" :title="cell.tip" />
      </div>
      <el-alert v-else-if="usageData" type="info" :closable="false" title="网段地址数超过 512，逐地址热图过密，请通过「地址分配记录」查看。" />
      <div class="heatmap-legend">
        <span><i class="dot" style="background:#722ed1" />网关</span>
        <span><i class="dot" style="background:#faad14" />保留段</span>
        <span><i class="dot" style="background:#1890ff" />静态</span>
        <span><i class="dot" style="background:#13c2c2" />DHCP</span>
        <span><i class="dot" style="background:#fa8c16" />保留分配</span>
        <span><i class="dot" style="background:#f0f0f0" />空闲</span>
      </div>
    </el-dialog>

    <el-dialog v-model="vlsmVisible" title="VLSM 划分子网" width="580px" :close-on-click-modal="false">
      <el-form label-width="90px">
        <el-form-item label="父网段"><el-input v-model="vlsmForm.parent" placeholder="如 10.0.0.0/16" /></el-form-item>
        <el-form-item label="目标掩码"><el-input-number v-model="vlsmForm.prefix" :min="8" :max="30" style="width: 100%" /></el-form-item>
        <el-form-item label="生成数量"><el-input-number v-model="vlsmForm.count" :min="1" :max="64" style="width: 100%" /></el-form-item>
        <el-form-item label="名称前缀"><el-input v-model="vlsmForm.namePrefix" placeholder="如 业务子网" /></el-form-item>
        <el-form-item label="所属部门">
          <el-select v-model="vlsmForm.department_id" clearable style="width: 100%">
            <el-option v-for="d in flatDepts" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="vlsm-actions">
        <el-button type="primary" plain @click="calcVlsm">生成子网</el-button>
      </div>
      <div v-if="vlsmResult.length" class="vlsm-list">
        <el-checkbox-group v-model="vlsmChecked">
          <el-checkbox v-for="item in vlsmResult" :key="item.network" :value="item.network" class="vlsm-item">
            {{ item.network }}（{{ item.name }}）
          </el-checkbox>
        </el-checkbox-group>
      </div>
      <template #footer>
        <el-button @click="vlsmVisible = false">取消</el-button>
        <el-button type="primary" :loading="vlsmSaving" :disabled="!vlsmChecked.length" @click="applyVlsm">
          登记所选子网（{{ vlsmChecked.length }}）
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { monitorApi } from '@/api/monitor'
import { userApi } from '@/api/users'
import { departmentApi } from '@/api/departments'

import { formatDateTime as fmt } from '@/utils/format'
const allocText = (t) => ({ static: '静态', dhcp: 'DHCP', reserved: '保留' }[t] || t)
const allocTag = (t) => ({ static: 'success', dhcp: 'primary', reserved: 'warning' }[t] || 'info')
const pct = (row) => (row.capacity ? Math.min(100, Math.round((row.used / row.capacity) * 100)) : 0)
const histText = (a) => ({ 'ipam:alloc:create': '分配', 'ipam:alloc:release': '释放', 'ipam:alloc:update': '修改' }[a] || a)
const histTag = (a) => ({ 'ipam:alloc:create': 'success', 'ipam:alloc:release': 'danger', 'ipam:alloc:update': 'warning' }[a] || 'info')

// ---- IP 工具函数 ----
const ipToInt = (ip) => ip.split('.').reduce((acc, b) => ((acc << 8) | parseInt(b, 10)) >>> 0, 0) >>> 0
const intToIp = (n) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255].join('.')
const parseCidr = (s) => {
  const [ip, p] = String(s).split('/')
  const prefix = parseInt(p, 10)
  if (!ip || isNaN(prefix) || prefix < 0 || prefix > 32) return null
  const parts = ip.split('.')
  if (parts.length !== 4 || parts.some((x) => !/^\d{1,3}$/.test(x) || Number(x) > 255)) return null
  return { int: ipToInt(ip), prefix }
}
const isIPv4 = (v) => /^\d{1,3}(\.\d{1,3}){3}$/.test(v) && v.split('.').every((x) => Number(x) <= 255)
const cidrValidator = (_rule, value, callback) => {
  if (!value) return callback()
  if (!parseCidr(value)) return callback(new Error('网段格式不正确，如 10.0.30.0/24'))
  callback()
}
const ipValidator = (_rule, value, callback) => {
  if (!value) return callback()
  if (!isIPv4(value)) return callback(new Error('IP 地址格式不正确'))
  callback()
}
const ipInNet = (ipInt, net) => ipInt >= net.int && ipInt < net.int + 2 ** (32 - net.prefix)
const parseReservedText = (text) =>
  String(text || '').split('\n').map((s) => s.trim()).filter(Boolean)
const reservedToText = (ranges) => (ranges || []).join('\n')

// VLSM：把父网段按目标掩码切成若干子网（父网段需按网络边界对齐）
function vlsmSplit(parentCidr, childPrefix, count) {
  const parent = parseCidr(parentCidr)
  if (!parent) throw new Error('父网段格式不正确')
  if (childPrefix <= parent.prefix) throw new Error(`目标掩码（/${childPrefix}）需大于父网段掩码（/${parent.prefix}）`)
  const childSize = 2 ** (32 - childPrefix)
  const out = []
  for (let i = 0; i < count; i++) {
    out.push(`${intToIp(parent.int + i * childSize)}/${childPrefix}`)
  }
  return out
}

const subnetLoading = ref(false)
const allocLoading = ref(false)
const subnets = ref([])
const allocs = ref([])
const allocTotal = ref(0)
const allocQuery = reactive({ page: 1, size: 10, keyword: '', subnet_id: null })
const flatDepts = ref([])
const users = ref([])
const devices = ref([])

const subnetVisible = ref(false)
const savingSubnet = ref(false)
const subnetFormRef = ref()
const subnetForm = reactive({ name: '', network: '', department_id: null, reserved_ranges_text: '' })
const subnetRules = {
  name: [{ required: true, message: '请输入子网名称', trigger: 'blur' }],
  network: [
    { required: true, message: '请输入网段', trigger: 'blur' },
    { validator: cidrValidator, trigger: 'blur' }
  ]
}
const subnetDelVisible = ref(false)
const subnetDelTarget = ref(null)
const subnetDelReason = ref('')
const subnetRemoving = ref(false)

const subnetEditVisible = ref(false)
const subnetEditTarget = ref(null)
const subnetEditForm = reactive({ name: '', gateway: '', vlan_id: null, department_id: null, reserved_ranges_text: '' })
const savingSubnetEdit = ref(false)

const allocVisible = ref(false)
const savingAlloc = ref(false)
const recycling = ref(false)
const allocFormRef = ref()
const allocForm = reactive({ subnet_id: null, ip_address: '', allocation_type: 'static', purpose: '', allocated_to: null, device_id: null })
const allocRules = {
  subnet_id: [{ required: true, message: '请选择子网', trigger: 'change' }],
  ip_address: [{ validator: ipValidator, trigger: 'blur' }]
}

const allocEditVisible = ref(false)
const allocEditTarget = ref(null)
const allocEditForm = reactive({ purpose: '', allocation_type: 'static', allocated_to: null, device_id: null })
const savingAllocEdit = ref(false)

const historyVisible = ref(false)
const historyIp = ref('')
const historyList = ref([])
const historyLoading = ref(false)

const usageVisible = ref(false)
const usageData = ref(null)

const vlsmVisible = ref(false)
const vlsmForm = reactive({ parent: '', prefix: 24, count: 4, namePrefix: '', department_id: null })
const vlsmResult = ref([])
const vlsmChecked = ref([])
const vlsmSaving = ref(false)

// 网络发现
const discLoading = ref(false)
const discovering = ref(false)
const discList = ref([])
const discTotal = ref(0)
const discQuery = reactive({ page: 1, size: 8, subnet_id: null, network: '' })
const discPickSubnet = ref(null)  // 已登记子网快捷选择（选中后回填网段输入框）
const discResult = ref(null)
const discChecked = ref([])
const discStatusText = (s) => ({ pending: '排队中', running: '扫描中', completed: '已完成', failed: '失败' }[s] || s)
const discStatusTag = (s) => ({ pending: 'info', running: 'warning', completed: 'success', failed: 'danger' }[s] || 'info')

// 从发现结果 hosts 元数据反查某 IP 的 MAC/厂商（手动输入网段扫描时终端带 MAC）
function discMeta(ip) {
  return (discResult.value?.hosts || []).find((h) => h.ip === ip) || {}
}

function onPickSubnet(id) {
  const s = subnets.value.find((x) => x.id === id)
  if (s) {
    discQuery.network = s.network
    discQuery.subnet_id = s.id
  }
}
let discPollTimer = null
let discPollId = null
let discPollTries = 0

function stopDiscoveryPolling() {
  if (discPollTimer) { clearInterval(discPollTimer); discPollTimer = null }
  discPollId = null
}

// 热图单元格
const usageCells = computed(() => {
  const d = usageData.value
  if (!d) return []
  const net = parseCidr(d.network)
  if (!net || 2 ** (32 - net.prefix) > 512) return []
  const allocByIp = new Map((d.allocations || []).map((a) => [a.ip, a]))
  const reservedNets = (d.reserved_ranges || []).map(parseCidr).filter(Boolean)
  const gw = d.gateway
  const count = 2 ** (32 - net.prefix)
  const cells = []
  for (let i = 0; i < count; i++) {
    const ip = intToIp(net.int + i)
    const ipInt = net.int + i
    const inReserved = reservedNets.some((rn) => ipInNet(ipInt, rn))
    const alloc = allocByIp.get(ip)
    let color = '#f0f0f0'
    let tip = `${ip} 空闲`
    if (gw === ip) { color = '#722ed1'; tip = `${ip} 网关` }
    else if (inReserved) { color = '#faad14'; tip = `${ip} 保留段` }
    else if (alloc) {
      color = alloc.allocation_type === 'dhcp' ? '#13c2c2' : alloc.allocation_type === 'reserved' ? '#fa8c16' : '#1890ff'
      tip = `${ip} ${allocText(alloc.allocation_type)}${alloc.purpose ? ' · ' + alloc.purpose : ''}`
    }
    cells.push({ ip, color, tip })
  }
  return cells
})

async function loadSubnets() {
  subnetLoading.value = true
  try { subnets.value = await monitorApi.subnets() } finally { subnetLoading.value = false }
}

async function loadAlloc() {
  allocLoading.value = true
  try {
    const data = await monitorApi.allocations({
      page: allocQuery.page, size: allocQuery.size,
      keyword: allocQuery.keyword || undefined,
      subnet_id: allocQuery.subnet_id || undefined
    })
    allocs.value = data.items
    allocTotal.value = data.total
  } finally { allocLoading.value = false }
}

async function loadOptions() {
  try {
    const roots = await departmentApi.tree()
    const flat = []
    const walk = (nodes, depth = 0) => {
      nodes.forEach((n) => {
        flat.push({ ...n, name: (depth ? '　'.repeat(depth) : '') + n.name })
        if (n.children?.length) walk(n.children, depth + 1)
      })
    }
    walk(Array.isArray(roots) ? roots : [])
    flatDepts.value = flat
  } catch { /* 忽略 */ }
  try { users.value = (await userApi.list({ size: 500 })).items } catch { /* 忽略 */ }
  try { devices.value = (await monitorApi.devices({ size: 500 })).items } catch { /* 忽略 */ }
}

function openSubnet() {
  Object.assign(subnetForm, { name: '', network: '', department_id: null, reserved_ranges_text: '' })
  subnetVisible.value = true
}

async function saveSubnet() {
  await subnetFormRef.value.validate()
  savingSubnet.value = true
  try {
    await monitorApi.createSubnet({
      name: subnetForm.name, network: subnetForm.network,
      department_id: subnetForm.department_id || undefined,
      reserved_ranges: parseReservedText(subnetForm.reserved_ranges_text) || undefined
    })
    ElMessage.success('子网已创建')
    subnetVisible.value = false
    loadSubnets()
  } catch { /* 拦截器已提示 */ } finally { savingSubnet.value = false }
}

function openDeleteSubnet(row) {
  subnetDelTarget.value = row
  subnetDelReason.value = ''
  subnetDelVisible.value = true
}

async function removeSubnet() {
  subnetRemoving.value = true
  try {
    const data = await monitorApi.deleteSubnet(subnetDelTarget.value.id, { reason: subnetDelReason.value || null })
    ElMessage.success(data.message)
    subnetDelVisible.value = false
    loadSubnets(); loadAlloc()
  } catch { /* 拦截器已提示 */ } finally { subnetRemoving.value = false }
}

function openEditSubnet(row) {
  subnetEditTarget.value = row
  Object.assign(subnetEditForm, {
    name: row.name, gateway: row.gateway || '', vlan_id: row.vlan_id ?? null,
    department_id: row.department_id ?? null, reserved_ranges_text: reservedToText(row.reserved_ranges)
  })
  subnetEditVisible.value = true
}

async function saveEditSubnet() {
  if (!subnetEditForm.name) { ElMessage.warning('子网名称不能为空'); return }
  if (subnetEditForm.gateway && !isIPv4(subnetEditForm.gateway)) { ElMessage.warning('网关 IP 格式不正确'); return }
  savingSubnetEdit.value = true
  try {
    await monitorApi.updateSubnet(subnetEditTarget.value.id, {
      name: subnetEditForm.name,
      gateway: subnetEditForm.gateway || undefined,
      vlan_id: subnetEditForm.vlan_id ?? undefined,
      department_id: subnetEditForm.department_id ?? undefined,
      reserved_ranges: parseReservedText(subnetEditForm.reserved_ranges_text) || []
    })
    ElMessage.success('子网已更新')
    subnetEditVisible.value = false
    loadSubnets()
  } catch { /* 拦截器已提示 */ } finally { savingSubnetEdit.value = false }
}

function openAlloc() {
  Object.assign(allocForm, { subnet_id: null, ip_address: '', allocation_type: 'static', purpose: '', allocated_to: null, device_id: null })
  allocVisible.value = true
}

async function saveAlloc() {
  await allocFormRef.value.validate()
  savingAlloc.value = true
  try {
    await monitorApi.createAllocation({
      ...allocForm,
      ip_address: allocForm.ip_address || undefined,
      allocated_to: allocForm.allocated_to || undefined,
      device_id: allocForm.device_id || undefined
    })
    ElMessage.success('地址已分配')
    allocVisible.value = false
    loadAlloc(); loadSubnets()
  } catch { /* 拦截器已提示 */ } finally { savingAlloc.value = false }
}

async function release(row) {
  try {
    await ElMessageBox.confirm(`确定释放地址 ${row.ip_address}？释放后该地址可立即重新分配。`, '释放确认', { type: 'warning' })
    await monitorApi.releaseAllocation(row.id)
    ElMessage.success('地址已释放')
    loadAlloc(); loadSubnets()
  } catch { /* 取消或失败 */ }
}

async function recycleLeases() {
  recycling.value = true
  try {
    const res = await monitorApi.recycleAllocations()
    ElMessage.success(res.recycled ? `已回收 ${res.recycled} 条过期租约` : '没有过期租约需要回收')
    loadAlloc(); loadSubnets()
  } catch { /* 拦截器已提示 */ } finally { recycling.value = false }
}

function openEditAlloc(row) {
  allocEditTarget.value = row
  Object.assign(allocEditForm, {
    purpose: row.purpose || '', allocation_type: row.allocation_type || 'static',
    allocated_to: row.allocated_to ?? null, device_id: row.device_id ?? null
  })
  allocEditVisible.value = true
}

async function saveEditAlloc() {
  savingAllocEdit.value = true
  try {
    const data = await monitorApi.updateAllocation(allocEditTarget.value.id, {
      purpose: allocEditForm.purpose || undefined,
      allocation_type: allocEditForm.allocation_type,
      allocated_to: allocEditForm.allocated_to || undefined,
      device_id: allocEditForm.device_id || undefined
    })
    ElMessage.success('分配已更新')
    allocEditVisible.value = false
    loadAlloc()
  } catch { /* 拦截器已提示 */ } finally { savingAllocEdit.value = false }
}

async function openHistory(row) {
  historyIp.value = row.ip_address
  historyList.value = []
  historyVisible.value = true
  historyLoading.value = true
  try {
    historyList.value = await monitorApi.allocationHistory(row.ip_address)
  } catch { /* 拦截器已提示 */ } finally { historyLoading.value = false }
}

function fmtDetail(h) {
  const d = h.detail || {}
  if (h.action === 'ipam:alloc:update') {
    const c = d.changes || {}
    const parts = Object.entries(c).map(([k, v]) => {
      const label = { purpose: '用途', allocation_type: '类型', allocated_to: '使用人', device_id: '设备', expires_at: '到期' }[k] || k
      return `${label}: ${v}`
    })
    return parts.length ? '变更 ' + parts.join('，') : ''
  }
  if (h.action === 'ipam:alloc:create') return `分配于子网 ${d.subnet || '—'}`
  return ''
}

async function openUsage(row) {
  usageData.value = null
  usageVisible.value = true
  try { usageData.value = await monitorApi.subnetUsage(row.id) } catch { /* 拦截器已提示 */ }
}

function openVlsm() {
  Object.assign(vlsmForm, { parent: '', prefix: 24, count: 4, namePrefix: '', department_id: null })
  vlsmResult.value = []
  vlsmChecked.value = []
  vlsmVisible.value = true
}

function calcVlsm() {
  try {
    const nets = vlsmSplit(vlsmForm.parent, vlsmForm.prefix, vlsmForm.count)
    vlsmResult.value = nets.map((network, i) => ({ network, name: vlsmForm.namePrefix ? `${vlsmForm.namePrefix}-${i + 1}` : network }))
    vlsmChecked.value = []
    if (!vlsmForm.namePrefix) ElMessage.warning('建议填写名称前缀，便于登记后识别')
  } catch (e) {
    ElMessage.warning(e.message)
  }
}

async function applyVlsm() {
  vlsmSaving.value = true
  try {
    for (const item of vlsmResult.value) {
      if (!vlsmChecked.value.includes(item.network)) continue
      await monitorApi.createSubnet({
        name: item.name, network: item.network,
        department_id: vlsmForm.department_id || undefined
      })
    }
    ElMessage.success(`已登记 ${vlsmChecked.value.length} 个子网`)
    vlsmVisible.value = false
    loadSubnets()
  } catch { /* 拦截器已提示 */ } finally { vlsmSaving.value = false }
}

// ---------- 网络发现 ----------
async function loadDiscoveries() {
  discLoading.value = true
  try {
    const data = await monitorApi.discoveries({
      page: discQuery.page, size: discQuery.size,
      subnet_id: discQuery.subnet_id || undefined
    })
    discList.value = data.items
    discTotal.value = data.total
  } finally { discLoading.value = false }
}

async function startDiscovery() {
  if (discovering.value || !discQuery.network) return
  discovering.value = true
  discChecked.value = []
  discResult.value = null
  try {
    const data = await monitorApi.discoverSubnet({ network: discQuery.network, subnet_id: discQuery.subnet_id || null })
    stopDiscoveryPolling()
    discPollId = data.discovery_id
    discPollTries = 0
    ElMessage.info('发现已提交，后台扫描中…')
    discPollTimer = setInterval(pollDiscovery, 2000)
  } catch { /* 拦截器已提示 */ } finally { discovering.value = false }
}

async function pollDiscovery() {
  if (!discPollId) return
  discPollTries += 1
  let d
  try { d = await monitorApi.discovery(discPollId) } catch { /* 单次失败忽略，继续轮询 */ }
  if (d) discResult.value = d
  if (d?.scan_status === 'completed') {
    stopDiscoveryPolling()
    ElMessage.success(`发现完成：在线 ${d.online_ips.length} 台，幽灵设备 ${d.unregistered_ips.length} 台`)
    loadDiscoveries()
  } else if (d?.scan_status === 'failed') {
    stopDiscoveryPolling()
    ElMessage.error(`发现失败：${d.error || '未知错误'}`)
    loadDiscoveries()
  } else if (discPollTries >= 150) {  // 2s × 150 ≈ 5 分钟（大子网主机发现较慢）
    stopDiscoveryPolling()
    ElMessage.warning('等待超时，请到发现历史查看状态')
    loadDiscoveries()
  }
}

async function viewDiscovery(row) {
  try {
    const d = await monitorApi.discovery(row.id)
    discResult.value = d
    if (d.scan_status === 'pending' || d.scan_status === 'running') {
      stopDiscoveryPolling()
      discPollId = d.id
      discPollTries = 0
      discPollTimer = setInterval(pollDiscovery, 2000)
    }
  } catch { /* 拦截器已提示 */ }
}

function toggleAllGhosts() {
  const all = discResult.value?.unregistered_ips || []
  discChecked.value = discChecked.value.length === all.length ? [] : [...all]
}

async function registerGhosts() {
  const ips = [...discChecked.value]
  if (!ips.length) { ElMessage.warning('请先勾选要登记的终端'); return }
  try {
    const msg = discResult.value.subnet_name
      ? `确认将 ${ips.length} 台终端登记为设备并创建 DHCP 分配？`
      : `确认将 ${ips.length} 台终端登记为设备并创建 DHCP 分配？（未登记网段将自动创建子网，掩码固化进台账）`
    await ElMessageBox.confirm(msg, '登记确认', { type: 'warning' })
    const data = await monitorApi.registerDiscovery(discResult.value.id, { ips })
    ElMessage.success(`已登记 ${data.registered} 台终端设备`)
    discChecked.value = []
    loadSubnets(); loadAlloc()
    // 刷新结果：已登记的从「幽灵设备」移到「在线已登记」
    discResult.value = await monitorApi.discovery(discResult.value.id)
  } catch { /* 取消或失败 */ }
}

onMounted(() => { loadSubnets(); loadAlloc(); loadOptions(); loadDiscoveries() })
onBeforeUnmount(stopDiscoveryPolling)
</script>

<style scoped>
.head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 12px; }
.head h3 { margin: 0 0 4px; }
.sub { margin: 0; color: #909399; font-size: 13px; }
.alloc-card { margin-top: 14px; }
.disc-card { margin-top: 14px; }
.disc-result { border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 12px; margin-bottom: 14px; }
.disc-result-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.disc-subnet { font-weight: 600; }
.disc-err { flex-basis: 100%; }
.disc-group { margin-bottom: 12px; }
.disc-group-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.disc-ips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.disc-ip { margin-right: 0; }
.disc-mac { font-weight: 400; }
.ghost-ip { color: #f56c6c; }
.ghost-num { color: #f56c6c; font-weight: 600; }
.disc-history { margin-top: 10px; }
.alloc-title { margin: 0; font-size: 16px; }
.ops { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.muted { color: #a8abb2; font-size: 12px; margin-left: 8px; }
.pager { margin-top: 14px; justify-content: flex-end; }
.auto-tip { margin-bottom: 2px; }
.del-box .del-alert { margin: 12px 0; }
.del-box .el-form-item { margin-bottom: 0; }
.res-tag { margin-right: 4px; }
.hist-title { font-weight: 600; margin-bottom: 12px; }
.hist-item { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.hist-op { color: #606266; font-size: 13px; }
.hist-detail { width: 100%; color: #909399; font-size: 12px; margin-top: 4px; }
.usage-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }
.usage-name { font-weight: 600; }
.usage-meta { color: #909399; font-size: 13px; }
.heatmap { display: flex; flex-wrap: wrap; gap: 2px; }
.cell { width: 12px; height: 12px; border-radius: 2px; border: 1px solid #fff; }
.heatmap-legend { display: flex; gap: 16px; margin-top: 12px; flex-wrap: wrap; }
.heatmap-legend span { display: inline-flex; align-items: center; font-size: 12px; color: #606266; }
.dot { width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; display: inline-block; }
.vlsm-actions { margin: 12px 0; }
.vlsm-list { border: 1px solid #ebeef5; border-radius: 4px; padding: 10px 12px; max-height: 260px; overflow: auto; }
.vlsm-item { display: flex; width: 100%; margin-right: 0; margin-bottom: 4px; }
</style>
