import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'
import { taskerApi } from '@/apis/tasker'

const ACTIVE_STATUSES = new Set(['pending', 'running', 'queued'])

const toTask = (raw = {}) => ({
  id: raw.id,
  name: raw.name || '后台任务',
  type: raw.type || 'general',
  status: raw.status || 'pending',
  progress: raw.progress ?? 0,
  message: raw.message || '',
  created_at: raw.created_at,
  updated_at: raw.updated_at,
  started_at: raw.started_at,
  completed_at: raw.completed_at,
  payload: raw.payload || {},
  result: raw.result,
  error: raw.error,
  cancel_requested: raw.cancel_requested || false
})

export const useTaskerStore = defineStore('tasker', () => {
  const tasks = ref([])
  const loading = ref(false)
  const lastError = ref(null)
  const isPolling = ref(false)
  const isDrawerOpen = ref(false)
  let pollingTimer = null

  const sortedTasks = computed(() => {
    return [...tasks.value].sort((a, b) => {
      if (!a.created_at || !b.created_at) return 0
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    })
  })

  const activeCount = computed(() => sortedTasks.value.filter(task => ACTIVE_STATUSES.has(task.status)).length)

  function upsertTask(rawTask) {
    if (!rawTask || !rawTask.id) return
    const task = toTask(rawTask)
    const index = tasks.value.findIndex(item => item.id === task.id)
    if (index >= 0) {
      tasks.value.splice(index, 1, { ...tasks.value[index], ...task })
    } else {
      tasks.value.unshift(task)
    }
  }

  async function loadTasks(params = {}) {
    loading.value = true
    lastError.value = null
    try {
      const response = await taskerApi.fetchTasks(params)
      const taskList = response?.tasks || []
      tasks.value = taskList.map(toTask)
    } catch (error) {
      console.error('加载任务列表失败', error)
      lastError.value = error
    } finally {
      loading.value = false
    }
  }

  async function refreshTask(taskId) {
    if (!taskId) return
    try {
      const response = await taskerApi.fetchTaskDetail(taskId)
      if (response?.task) {
        upsertTask(response.task)
      }
    } catch (error) {
      console.error(`刷新任务 ${taskId} 详情失败`, error)
      lastError.value = error
    }
  }

  async function cancelTask(taskId) {
    if (!taskId) return
    try {
      await taskerApi.cancelTask(taskId)
      message.success('取消任务成功')
      await refreshTask(taskId)
    } catch (error) {
      console.error(`取消任务 ${taskId} 失败`, error)
      message.error(error?.message || '取消任务失败')
    }
  }

  function registerQueuedTask({ task_id, name, task_type, message: msg, payload } = {}) {
    if (!task_id) return
    const now = new Date().toISOString()
    upsertTask({
      id: task_id,
      name: name || '后台任务',
      type: task_type || 'manual',
      status: 'queued',
      progress: 0,
      message: msg || '任务已排队',
      created_at: now,
      updated_at: now,
      payload: payload || {}
    })
  }

  function openDrawer() {
    isDrawerOpen.value = true
  }

  function closeDrawer() {
    isDrawerOpen.value = false
  }

  function toggleDrawer() {
    isDrawerOpen.value = !isDrawerOpen.value
  }

  function startPolling(interval = 5000) {
    if (pollingTimer) return
    isPolling.value = true
    pollingTimer = setInterval(() => {
      loadTasks()
    }, interval)
  }

  function stopPolling() {
    if (pollingTimer) {
      clearInterval(pollingTimer)
      pollingTimer = null
    }
    isPolling.value = false
  }

  function reset() {
    stopPolling()
    tasks.value = []
    lastError.value = null
    isDrawerOpen.value = false
  }

  return {
    isDrawerOpen,
    tasks,
    sortedTasks,
    loading,
    lastError,
    activeCount,
    isPolling,
    loadTasks,
    refreshTask,
    cancelTask,
    registerQueuedTask,
    startPolling,
    stopPolling,
    reset,
    openDrawer,
    closeDrawer,
    toggleDrawer
  }
})
