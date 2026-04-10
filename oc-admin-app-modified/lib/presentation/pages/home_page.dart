import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../providers/instance_provider.dart';
import '../providers/theme_provider.dart';
import '../widgets/instance_card.dart';
import 'add_instance_page.dart';
import 'instance_detail_page.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _selectedIndex = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<InstanceProvider>().loadInstances();
      context.read<InstanceProvider>().startAutoRefresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _selectedIndex,
        children: [
          _buildDashboard(),
          _buildSettingsTab(),
        ],
      ),
      floatingActionButton: _selectedIndex == 0
          ? FloatingActionButton(
              onPressed: () => _showAddInstanceSheet(context),
              child: const Icon(Icons.add),
            )
          : null,
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (i) => setState(() => _selectedIndex = i),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard),
            label: '虾厂',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings),
            label: '设置',
          ),
        ],
      ),
    );
  }

  void _showAddInstanceSheet(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => const AddInstanceBottomSheet(),
    );
  }

  Widget _buildDashboard() {
    return Consumer<InstanceProvider>(
      builder: (context, provider, _) {
        if (provider.status == InstanceStatus.loading) {
          return const Center(child: CircularProgressIndicator());
        }

        final total = provider.instances.length;
        final online = provider.onlineInstances.length;
        final offline = provider.offlineInstances.length;

        return RefreshIndicator(
          onRefresh: provider.loadInstances,
          child: CustomScrollView(
            slivers: [
              SliverAppBar(
                floating: true,
                title: const Text('虾厂'),
                centerTitle: true,
                backgroundColor: Theme.of(context).colorScheme.surface,
                surfaceTintColor: Colors.transparent,
              ),
              SliverPadding(
                padding: const EdgeInsets.all(16),
                sliver: SliverToBoxAdapter(
                  child: Row(
                    children: [
                      Expanded(
                        child: _StatCard(
                          title: '总计',
                          value: '$total',
                          icon: Icons.dns_outlined,
                          color: Theme.of(context).colorScheme.primary,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: _StatCard(
                          title: '在线',
                          value: '$online',
                          icon: Icons.check_circle_outline,
                          color: Colors.green,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: _StatCard(
                          title: '离线',
                          value: '$offline',
                          icon: Icons.cancel_outlined,
                          color: Colors.grey,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              if (provider.onlineInstances.isNotEmpty) ...[
                SliverPadding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  sliver: SliverToBoxAdapter(
                    child: Text(
                      '在线',
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.w600,
                            color: Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                    ),
                  ),
                ),
                SliverPadding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  sliver: SliverList(
                    delegate: SliverChildBuilderDelegate(
                      (context, index) {
                        final instance = provider.onlineInstances[index];
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: InstanceCard(
                            instance: instance,
                            onTap: () => _openInstanceDetail(instance.instanceId),
                          ),
                        );
                      },
                      childCount: provider.onlineInstances.length,
                    ),
                  ),
                ),
              ],
              if (provider.offlineInstances.isNotEmpty) ...[
                SliverPadding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  sliver: SliverToBoxAdapter(
                    child: Text(
                      '离线',
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.w600,
                            color: Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                    ),
                  ),
                ),
                SliverPadding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  sliver: SliverList(
                    delegate: SliverChildBuilderDelegate(
                      (context, index) {
                        final instance = provider.offlineInstances[index];
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: InstanceCard(
                            instance: instance,
                            onTap: () => _openInstanceDetail(instance.instanceId),
                          ),
                        );
                      },
                      childCount: provider.offlineInstances.length,
                    ),
                  ),
                ),
              ],
              if (provider.instances.isEmpty)
                SliverFillRemaining(
                  hasScrollBody: false,
                  child: Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          Icons.dns_outlined,
                          size: 56,
                          color: Theme.of(context).colorScheme.outline,
                        ),
                        const SizedBox(height: 16),
                        Text(
                          '暂无绑定实例',
                          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                color: Theme.of(context).colorScheme.outline,
                              ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          '点击右下角 + 添加实例',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                color: Theme.of(context).colorScheme.outline,
                              ),
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildSettingsTab() {
    return Consumer<AuthProvider>(
      builder: (context, authProvider, _) {
        return CustomScrollView(
          slivers: [
            SliverAppBar(
              floating: true,
              title: const Text('设置'),
              centerTitle: true,
              backgroundColor: Theme.of(context).colorScheme.surface,
              surfaceTintColor: Colors.transparent,
            ),
            SliverPadding(
              padding: const EdgeInsets.all(16),
              sliver: SliverList(
                delegate: SliverChildListDelegate([
                  const SizedBox(height: 16),
                  // User info card
                  GestureDetector(
                    onTap: authProvider.user?.verified != true
                        ? () => _showResendVerificationDialog(context, authProvider)
                        : null,
                    child: Container(
                      padding: const EdgeInsets.all(20),
                      decoration: BoxDecoration(
                        color: Theme.of(context).colorScheme.surfaceContainerHighest.withAlpha(128),
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: Row(
                        children: [
                          CircleAvatar(
                            radius: 28,
                            backgroundColor: Theme.of(context).colorScheme.primaryContainer,
                            child: Text(
                              (authProvider.user?.name?.isNotEmpty == true
                                      ? authProvider.user!.name!.substring(0, 1)
                                      : (authProvider.user?.email ?? 'U'))
                                  .toUpperCase(),
                              style: TextStyle(
                                fontSize: 20,
                                fontWeight: FontWeight.w600,
                                color: Theme.of(context).colorScheme.onPrimaryContainer,
                              ),
                            ),
                          ),
                          const SizedBox(width: 16),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Flexible(
                                      child: Text(
                                        authProvider.user?.name?.isNotEmpty == true
                                            ? authProvider.user!.name!
                                            : '未设置用户名',
                                        style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                              fontWeight: FontWeight.w600,
                                            ),
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ),
                                    const SizedBox(width: 8),
                                    _buildVerificationBadge(context, authProvider.user?.verified ?? false),
                                  ],
                                ),
                                const SizedBox(height: 2),
                                Text(
                                  authProvider.user?.email ?? '',
                                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                                      ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 32),
                  // Theme mode switcher
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Theme.of(context).colorScheme.surfaceContainerHighest.withAlpha(128),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Row(
                      children: [
                        Icon(
                          Icons.brightness_6,
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            '界面模式',
                            style: Theme.of(context).textTheme.bodyLarge,
                          ),
                        ),
                        SegmentedButton<ThemeMode>(
                          segments: const [
                            ButtonSegment(value: ThemeMode.system, icon: Icon(Icons.brightness_auto)),
                            ButtonSegment(value: ThemeMode.light, icon: Icon(Icons.light_mode)),
                            ButtonSegment(value: ThemeMode.dark, icon: Icon(Icons.dark_mode)),
                          ],
                          selected: {context.watch<ThemeProvider>().themeMode},
                          onSelectionChanged: (Set<ThemeMode> selection) {
                            context.read<ThemeProvider>().setThemeMode(selection.first);
                          },
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 32),
                  // Logout button
                  OutlinedButton(
                    onPressed: () {
                      showDialog(
                        context: context,
                        builder: (ctx) => AlertDialog(
                          title: const Text('退出登录'),
                          content: const Text('确定要退出登录吗？'),
                          actions: [
                            TextButton(
                              onPressed: () => Navigator.pop(ctx),
                              child: const Text('取消'),
                            ),
                            FilledButton(
                              style: FilledButton.styleFrom(
                                backgroundColor: Theme.of(context).colorScheme.error,
                              ),
                              onPressed: () {
                                Navigator.pop(ctx);
                                context.read<AuthProvider>().logout();
                              },
                              child: const Text('退出'),
                            ),
                          ],
                        ),
                      );
                    },
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(16),
                      ),
                      side: BorderSide(color: Theme.of(context).colorScheme.outline.withAlpha(128)),
                      backgroundColor: Theme.of(context).colorScheme.surfaceContainerHighest.withAlpha(60),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          Icons.logout_outlined,
                          color: Theme.of(context).colorScheme.onSurface,
                          size: 20,
                        ),
                        const SizedBox(width: 8),
                        Text(
                          '退出登录',
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w500,
                            color: Theme.of(context).colorScheme.onSurface,
                          ),
                        ),
                      ],
                    ),
                  ),
                ]),
              ),
            ),
          ],
        );
      },
    );
  }

  void _openInstanceDetail(String instanceId) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => InstanceDetailPage(instanceId: instanceId),
      ),
    );
  }

  Widget _buildVerificationBadge(BuildContext context, bool verified) {
    if (verified) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          color: Colors.green.shade100,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          '已验证',
          style: TextStyle(
            fontSize: 11,
            color: Colors.green.shade700,
            fontWeight: FontWeight.w500,
          ),
        ),
      );
    } else {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          color: Colors.orange.shade100,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          '未验证',
          style: TextStyle(
            fontSize: 11,
            color: Colors.orange.shade700,
            fontWeight: FontWeight.w500,
          ),
        ),
      );
    }
  }

  void _showResendVerificationDialog(BuildContext context, AuthProvider authProvider) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('验证邮箱'),
        content: const Text('您的邮箱尚未验证。点击发送验证邮件到您的邮箱。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () async {
              Navigator.pop(ctx);
              final success = await authProvider.resendVerificationEmail();
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(success ? '验证邮件已发送' : '发送失败，请稍后重试'),
                    backgroundColor: success ? Colors.green : Colors.red,
                  ),
                );
              }
            },
            child: const Text('发送'),
          ),
        ],
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;
  final Color color;

  const _StatCard({
    required this.title,
    required this.value,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: color.withAlpha(25),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        children: [
          Icon(icon, color: color, size: 24),
          const SizedBox(height: 8),
          Text(
            value,
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: color,
                ),
          ),
          const SizedBox(height: 2),
          Text(
            title,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
        ],
      ),
    );
  }
}

/// 新增：添加实例的底部弹窗
class AddInstanceBottomSheet extends StatefulWidget {
  const AddInstanceBottomSheet({super.key});

  @override
  State<AddInstanceBottomSheet> createState() => _AddInstanceBottomSheetState();
}

class _AddInstanceBottomSheetState extends State<AddInstanceBottomSheet> with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      height: MediaQuery.of(context).size.height * 0.85,
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
      ),
      child: Column(
        children: [
          // 拖动条
          Container(
            margin: const EdgeInsets.only(top: 12),
            width: 40,
            height: 4,
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.outline.withAlpha(100),
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          // Tab 头
          Padding(
            padding: const EdgeInsets.all(16),
            child: TabBar(
              controller: _tabController,
              tabs: const [
                Tab(text: '快速添加'),
                Tab(text: '手动添加'),
              ],
              labelStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
              unselectedLabelStyle: const TextStyle(fontWeight: FontWeight.normal, fontSize: 15),
              indicator: BoxDecoration(
                color: Theme.of(context).colorScheme.primaryContainer,
                borderRadius: BorderRadius.circular(12),
              ),
              indicatorSize: TabBarIndicatorSize.label,
              dividerColor: Colors.transparent,
            ),
          ),
          // Tab 内容
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: const [
                _QuickAddTab(),
                AddInstancePage(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 快速添加 Tab
class _QuickAddTab extends StatelessWidget {
  const _QuickAddTab();

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 标题
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.primaryContainer.withAlpha(50),
              borderRadius: BorderRadius.circular(16),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(
                      Icons.flash_on,
                      color: Theme.of(context).colorScheme.primary,
                    ),
                    const SizedBox(width: 8),
                    Text(
                      '快速添加 WatchClaw 实例',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w600,
                          ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  '按照以下步骤，快速将 OpenClaw 设备绑定到你的账号',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),

          // 步骤 1
          _StepCard(
            stepNum: '1',
            title: '安装 WatchClaw 插件',
            content: '在 OpenClaw 手机 app 中安装 WatchClaw 插件，并按照指引完成基础配置。',
            icon: Icons.mobile_screen_share,
          ),
          const SizedBox(height: 16),

          // 步骤 2
          _StepCard(
            stepNum: '2',
            title: '复制 Token',
            content: '点击下方按钮，复制你的账号 Token。',
            icon: Icons.copy,
            child: _TokenCopyButton(),
          ),
          const SizedBox(height: 16),

          // 步骤 3
          _StepCard(
            stepNum: '3',
            title: '发送绑定指令给 OpenClaw',
            content: '将 Token 发送给 OpenClaw，让它自动完成实例注册和绑定。',
            icon: Icons.send,
            child: _OpenClawPromptCard(),
          ),
          const SizedBox(height: 24),

          // 提示
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceContainerHighest.withAlpha(128),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: [
                Icon(
                  Icons.info_outline,
                  size: 20,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    '绑定完成后，实例将自动出现在虾厂列表中',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _StepCard extends StatelessWidget {
  final String stepNum;
  final String title;
  final String content;
  final IconData icon;
  final Widget? child;

  const _StepCard({
    required this.stepNum,
    required this.title,
    required this.content,
    required this.icon,
    this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest.withAlpha(128),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.primary,
                  shape: BoxShape.circle,
                ),
                child: Center(
                  child: Text(
                    stepNum,
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w600,
                      fontSize: 14,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Icon(icon, size: 20, color: Theme.of(context).colorScheme.primary),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            content,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          if (child != null) ...[
            const SizedBox(height: 16),
            child!,
          ],
        ],
      ),
    );
  }
}

class _TokenCopyButton extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Consumer<AuthProvider>(
      builder: (context, authProvider, _) {
        return FutureBuilder<String?>(
          future: authProvider.getRelayToken(),
          builder: (context, snapshot) {
            final token = snapshot.data;
            if (token == null || token.isEmpty) {
              return OutlinedButton.icon(
                onPressed: () async {
                  final newToken = await authProvider.regenerateRelayToken();
                  if (context.mounted && newToken != null) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Token 已生成')),
                    );
                  }
                },
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('生成 Token'),
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                ),
              );
            }
            return OutlinedButton.icon(
              onPressed: () {
                Clipboard.setData(ClipboardData(text: token));
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Token 已复制到剪贴板')),
                );
              },
              icon: const Icon(Icons.copy, size: 18),
              label: const Text('复制 Token'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              ),
            );
          },
        );
      },
    );
  }
}

class _OpenClawPromptCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Consumer<AuthProvider>(
      builder: (context, authProvider, _) {
        return FutureBuilder<String?>(
          future: authProvider.getRelayToken(),
          builder: (context, snapshot) {
            final token = snapshot.data ?? '[YOUR_TOKEN]';
            return Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '发送以下指令给 OpenClaw：',
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: SelectableText(
                      '绑定 Pebble Relay 实例，Token: $token',
                      style: TextStyle(
                        fontFamily: 'monospace',
                        fontSize: 12,
                        color: Colors.black87,
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  TextButton.icon(
                    onPressed: () {
                      Clipboard.setData(ClipboardData(text: '绑定 Pebble Relay 实例，Token: $token'));
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('指令已复制')),
                      );
                    },
                    icon: const Icon(Icons.copy, size: 16),
                    label: const Text('复制指令'),
                    style: TextButton.styleFrom(
                      padding: EdgeInsets.zero,
                      minimumSize: Size.zero,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }
}
