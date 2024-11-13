#!/bin/bash

# 创建数据库文件
DB_FILE="users.db"

# 创建用户表的函数
create_table() {
    sqlite3 "$DB_FILE" <<EOF
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    key TEXT NOT NULL
);
EOF
}

# 列出所有用户的函数
list_users() {
    echo "当前用户列表："
    sqlite3 "$DB_FILE" "SELECT id, name FROM users;"
}

# 添加用户的函数
add_user() {
    read -p "请输入用户名: " username
    read -p "请输入密钥: " userkey

    # 插入新用户
    if sqlite3 "$DB_FILE" "INSERT INTO users (name, key) VALUES ('$username', '$userkey');" ; then
        echo "用户 '$username' 添加成功。"
    else
        echo "添加用户 '$username' 失败，可能是用户名已存在。"
    fi
}

# 删除用户的函数
delete_user() {
    read -p "请输入要删除的用户ID: " user_id

    # 删除用户
    if sqlite3 "$DB_FILE" "DELETE FROM users WHERE id = $user_id;" ; then
        echo "用户ID '$user_id' 删除成功。"
    else
        echo "删除用户ID '$user_id' 失败，可能是用户不存在。"
    fi
}

# 主菜单函数
main_menu() {
    create_table  # 确保表存在
    while true; do
        echo "请选择操作："
        echo "1. 列出用户"
        echo "2. 增加用户"
        echo "3. 删除用户"
        echo "4. 退出"
        read -p "输入选项: " option

        case $option in
            1) list_users ;;
            2) add_user ;;
            3) delete_user ;;
            4) echo "退出程序"; exit 0 ;;
            *) echo "无效选项，请重试。" ;;
        esac
        echo ""  # 输出空行以增强可读性
    done
}

# 运行主菜单
main_menu