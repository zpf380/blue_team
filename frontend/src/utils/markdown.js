import DOMPurify from 'dompurify'
import hljs from 'highlight.js'
import { marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import 'highlight.js/styles/github.css'

// marked v18 起使用 marked-highlight 扩展实现代码高亮
marked.use(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang }).value
      return hljs.highlightAuto(code).value
    }
  })
)

marked.setOptions({
  gfm: true,
  breaks: true
})

// Markdown → 白名单 HTML（DOMPurify 去除脚本/事件/危险标签，防 XSS）
export function renderMarkdown(text) {
  if (!text) return ''
  const html = marked.parse(String(text))
  return DOMPurify.sanitize(html)
}
