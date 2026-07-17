import { ElMessageBox } from 'element-plus/es/components/message-box/index.mjs'
import 'element-plus/es/components/message-box/style/css.mjs'

export async function confirmDestructiveAction(message: string, title = '确认操作'): Promise<boolean> {
  try {
    await ElMessageBox.confirm(message, title, {
      type: 'warning',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger'
    })
    return true
  } catch {
    return false
  }
}
