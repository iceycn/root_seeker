#!/bin/bash
# 同步 ruoyi-rootseeker-admin/sql 到 mysql-init/sql（当上游 SQL 更新时执行）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/../ruoyi-rootseeker-admin/sql"
DEST="$SCRIPT_DIR/mysql-init/sql"
[ -d "$SOURCE" ] && cp -f "$SOURCE"/*.sql "$DEST/" && echo "已同步 SQL 到 mysql-init/sql" || echo "源目录不存在: $SOURCE"
