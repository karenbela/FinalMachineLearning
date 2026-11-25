-- MIGRASI TAMBAHAN, AMAN UNTUK DATABASE YANG SUDAH BERISI DATA.
-- Tidak ada DROP DATABASE atau DELETE.
USE `edelweiss_prevention_db`;
CREATE TABLE IF NOT EXISTS `auth_sessions` (
  `session_id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  `user_id` BIGINT UNSIGNED NOT NULL,
  `token_hash` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
  `csrf_hash` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `created_at` DATETIME NOT NULL,
  `expires_at` DATETIME NOT NULL,
  `revoked_at` DATETIME NULL,
  CONSTRAINT `fk_auth_session_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  INDEX `idx_auth_session_user_expiry` (`user_id`, `expires_at`)
) ENGINE=InnoDB;
