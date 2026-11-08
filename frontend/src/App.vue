
<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'

import AppLayout from '@/components/layout/AppLayout.vue'

const route = useRoute()

const showAppLayout = computed(
  () => route.meta.access === 'user' || route.meta.access === 'admin',
)
</script>

<template>
  <AppLayout v-if="showAppLayout">
    <RouterView />
  </AppLayout>

  <RouterView v-else />
</template>
