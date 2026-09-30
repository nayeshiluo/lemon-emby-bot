const { createApp, ref, onMounted } = Vue
    createApp({
      setup() {
        const token = ref(sessionStorage.getItem('lemon_token') || '')
        const stats = ref({})
        const users = ref([])
        const genForm = ref({ value: 30, count: 5, card_type: 'days' })
        const generatedCodes = ref([])

        const getHeaders = () => ({
          'Content-Type': 'application/json',
          'x-admin-token': token.value
        })

        const fetchData = async () => {
          sessionStorage.setItem('lemon_token', token.value)
          try {
            const resStats = await fetch('/api/stats', { headers: getHeaders() })
            if (resStats.ok) stats.value = await resStats.json()
            const resUsers = await fetch('/api/users', { headers: getHeaders() })
            if (resUsers.ok) users.value = await resUsers.json()
          } catch (e) {
            console.error(e)
          }
        }

        const generateCodes = async () => {
          try {
            const res = await fetch('/api/codes/generate', {
              method: 'POST',
              headers: getHeaders(),
              body: JSON.stringify(genForm.value)
            })
            if (res.ok) {
              const data = await res.json()
              generatedCodes.value = data.codes
            }
          } catch (e) {
            console.error(e)
          }
        }

        const killSession = async (sessionId) => {
          if (!confirm('确定要阻断并踢出该播放会话吗？')) return
          try {
            await fetch('/api/sessions/kill', {
              method: 'POST',
              headers: getHeaders(),
              body: JSON.stringify({ session_id: sessionId })
            })
            fetchData()
          } catch (e) {
            console.error(e)
          }
        }

        onMounted(() => {
          fetchData()
          setInterval(fetchData, 10000)
        })

        return {
          token,
          stats,
          users,
          genForm,
          generatedCodes,
          fetchData,
          generateCodes,
          killSession
        }
      }
    }).mount('#app')
