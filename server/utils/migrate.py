"""
数据库迁移系统
"""

import os
import shutil
import sqlite3
from pathlib import Path

from src.utils import logger
from src.utils.datetime_utils import shanghai_now


class DatabaseMigrator:
    """数据库迁移器"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.backup_dir = os.path.join(os.path.dirname(db_path), "backups")
        self.migration_version_key = "migration_version"

    def ensure_backup_dir(self):
        """确保备份目录存在"""
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)

    def backup_database(self) -> str:
        """备份数据库文件"""
        if not os.path.exists(self.db_path):
            logger.info("数据库文件不存在，无需备份")
            return ""

        self.ensure_backup_dir()
        timestamp = shanghai_now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"server_backup_{timestamp}.db"
        backup_path = os.path.join(self.backup_dir, backup_filename)

        try:
            shutil.copy2(self.db_path, backup_path)
            logger.info(f"数据库已备份到: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"数据库备份失败: {e}")
            raise

    def get_current_version(self) -> int:
        """获取当前数据库版本"""
        if not os.path.exists(self.db_path):
            return 0

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 检查版本表是否存在
            cursor.execute("""
                                   SELECT name FROM sqlite_master
                                   WHERE type='table' AND name='migration_versions'            """)

            if not cursor.fetchone():
                # 版本表不存在，检查是否为旧版本数据库
                cursor.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='users'
                """)
                if cursor.fetchone():
                    # 用户表存在但版本表不存在，说明是旧版本
                    return 0
                else:
                    # 全新数据库
                    return 0

            # 获取当前版本
            cursor.execute("SELECT version FROM migration_versions ORDER BY version DESC LIMIT 1")
            result = cursor.fetchone()
            return result[0] if result else 0

        except Exception as e:
            logger.error(f"获取数据库版本失败: {e}")
            return 0
        finally:
            if "conn" in locals():
                conn.close()

    def set_version(self, version: int):
        """设置数据库版本"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 创建版本表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS migration_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """)

            # 插入版本记录
            cursor.execute(
                """
                INSERT INTO migration_versions (version, description)
                VALUES (?, ?)
            """,
                (version, f"Migration to version {version}"),
            )

            conn.commit()
            logger.info(f"数据库版本设置为: {version}")

        except Exception as e:
            logger.error(f"设置数据库版本失败: {e}")
            raise
        finally:
            if "conn" in locals():
                conn.close()

    def execute_migration(self, version: int, description: str, sql_commands: list[str]):
        """执行迁移"""
        logger.info(f"执行迁移 v{version}: {description}")

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 执行迁移SQL命令
            for sql in sql_commands:
                if sql.strip():  # 跳过空命令
                    logger.info(f"执行SQL: {sql}")
                    cursor.execute(sql)

            conn.commit()
            logger.info(f"迁移 v{version} 执行成功")

        except Exception as e:
            logger.error(f"迁移 v{version} 执行失败: {e}")
            raise
        finally:
            if "conn" in locals():
                conn.close()

    def check_column_exists(self, table_name: str, column_name: str) -> bool:
        """检查列是否存在"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [column[1] for column in cursor.fetchall()]
            return column_name in columns

        except Exception:
            return False
        finally:
            if "conn" in locals():
                conn.close()

    def run_migrations(self):
        """运行所有待执行的迁移"""
        current_version = self.get_current_version()
        latest_version = self.get_latest_migration_version()

        # 如果数据库已存在但没有版本表，创建版本表并设置为最新版本
        if current_version == 0 and latest_version > 0 and os.path.exists(self.db_path):
            # 检查users表是否已有新字段，如果有，说明是通过SQLAlchemy创建的
            required_columns = [
                "login_failed_count",
                "last_failed_login",
                "login_locked_until",
                "is_deleted",
                "deleted_at",
            ]
            if all(self.check_column_exists("users", column) for column in required_columns):
                # 字段已存在，直接设置为最新版本
                logger.info(f"检测到现有数据库已包含最新字段，设置版本为 v{latest_version}")
                self.set_version(latest_version)
                return

        if current_version >= latest_version:
            logger.info(f"数据库已是最新版本 v{current_version}")
            return

        logger.info(f"开始数据库迁移: v{current_version} -> v{latest_version}")

        # 备份数据库
        backup_path = self.backup_database()

        try:
            # 执行迁移
            migrations = self.get_migrations()
            has_executed_migrations = False

            for version, description, sql_commands in migrations:
                if version > current_version:
                    if sql_commands:  # 只有当有SQL命令时才执行迁移
                        self.execute_migration(version, description, sql_commands)
                        has_executed_migrations = True
                    else:
                        logger.info(f"迁移 v{version}: {description} - 无需执行，字段已存在")

                    # 无论是否有SQL命令，都设置版本
                    self.set_version(version)

            if has_executed_migrations:
                logger.info("数据库迁移完成")
            else:
                logger.info("数据库结构已是最新，仅更新版本记录")

        except Exception as e:
            logger.error(f"数据库迁移失败: {e}")
            if backup_path and os.path.exists(backup_path):
                logger.info(f"尝试从备份恢复: {backup_path}")
                try:
                    shutil.copy2(backup_path, self.db_path)
                    logger.info("数据库已从备份恢复")
                except Exception as restore_error:
                    logger.error(f"数据库恢复失败: {restore_error}")
            raise

    def get_latest_migration_version(self) -> int:
        """获取最新迁移版本号"""
        migrations = self.get_migrations()
        return max((version for version, _, _ in migrations), default=0)

    def get_migrations(self) -> list[tuple[int, str, list[str]]]:
        """获取所有迁移定义
        返回格式: [(version, description, [sql_commands])]
        """
        migrations = []

        # 迁移 v1: 为 users 表添加登录失败限制字段
        # 使用条件检查来避免重复添加字段
        v1_commands = []

        # 检查并添加 login_failed_count 字段
        if not self.check_column_exists("users", "login_failed_count"):
            v1_commands.append("ALTER TABLE users ADD COLUMN login_failed_count INTEGER NOT NULL DEFAULT 0")

        # 检查并添加 last_failed_login 字段
        if not self.check_column_exists("users", "last_failed_login"):
            v1_commands.append("ALTER TABLE users ADD COLUMN last_failed_login DATETIME")

        # 检查并添加 login_locked_until 字段
        if not self.check_column_exists("users", "login_locked_until"):
            v1_commands.append("ALTER TABLE users ADD COLUMN login_locked_until DATETIME")

        migrations.append((1, "为用户表添加登录失败限制字段", v1_commands))

        # 迁移 v2: 为 users 表添加软删除字段
        v2_commands: list[str] = []

        if not self.check_column_exists("users", "is_deleted"):
            v2_commands.append("ALTER TABLE users ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")

        if not self.check_column_exists("users", "deleted_at"):
            v2_commands.append("ALTER TABLE users ADD COLUMN deleted_at DATETIME")

        migrations.append((2, "为用户表添加软删除字段", v2_commands))

        # 未来的迁移可以在这里添加
        # migrations.append((
        #     2,
        #     "添加新功能相关表",
        #     [
        #         "CREATE TABLE new_feature (...)",
        #         "ALTER TABLE existing_table ADD COLUMN new_field ..."
        #     ]
        # ))

        return migrations


def validate_database_schema(db_path: str) -> tuple[bool, list[str]]:
    """验证数据库结构是否符合当前模型

    Returns:
        tuple: (是否符合, 缺失的字段列表)
    """
    if not os.path.exists(db_path):
        return False, ["数据库文件不存在"]

    missing_fields = []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 检查users表必需字段
        required_fields = {
            "users": [
                "id",
                "username",
                "user_id",
                "phone_number",
                "avatar",
                "password_hash",
                "role",
                "created_at",
                "last_login",
                "login_failed_count",
                "last_failed_login",
                "login_locked_until",
                "is_deleted",
                "deleted_at",
            ],
            "operation_logs": ["id", "user_id", "operation", "details", "ip_address", "timestamp"],
        }

        for table_name, fields in required_fields.items():
            # 检查表是否存在
            cursor.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name=?
            """,
                (table_name,),
            )

            if not cursor.fetchone():
                missing_fields.append(f"表 {table_name} 不存在")
                continue

            # 检查字段是否存在
            cursor.execute(f"PRAGMA table_info({table_name})")
            existing_columns = [column[1] for column in cursor.fetchall()]

            for field in fields:
                if field not in existing_columns:
                    missing_fields.append(f"表 {table_name} 缺少字段 {field}")

        return len(missing_fields) == 0, missing_fields

    except Exception as e:
        logger.error(f"验证数据库结构失败: {e}")
        return False, [f"验证失败: {str(e)}"]
    finally:
        if "conn" in locals():
            conn.close()


def check_and_migrate(db_path: str):
    """检查并执行数据库迁移"""
    # 先验证数据库结构
    is_valid, issues = validate_database_schema(db_path)

    if not is_valid:
        logger.warning("数据库结构不符合当前设计:")
        for issue in issues:
            logger.warning(f"  - {issue}")

        if os.path.exists(db_path):
            logger.info("建议运行迁移脚本: docker exec api-dev python /app/scripts/migrate_user_soft_delete.py")

    migrator = DatabaseMigrator(db_path)

    try:
        migrator.run_migrations()
        return True
    except Exception as e:
        logger.error(f"数据库迁移过程中发生错误: {e}")
        return False
