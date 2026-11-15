-- Run this in XAMPP phpMyAdmin → Import
-- ─────────────────────────────────────────────────────────────────
-- LAB SUBJECTS: suffix the name with _lab  (e.g. "MC_lab", "ADA_lab")
--   → Algorithm treats them as 2-period blocks, A1+A2 batches, lab rooms
-- THEORY SUBJECTS: no suffix  (e.g. "ADA", "DBMS")
--   → Single-period slots in theory classrooms only
-- ─────────────────────────────────────────────────────────────────

CREATE DATABASE IF NOT EXISTS timetable_db;
USE timetable_db;

CREATE TABLE IF NOT EXISTS users (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50)  NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role     ENUM('admin','viewer') DEFAULT 'admin'
);

CREATE TABLE IF NOT EXISTS teachers (
    id   INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    name     VARCHAR(50) NOT NULL,
    capacity INT DEFAULT 60
    -- Rooms whose name contains "lab" (case-insensitive) are used for lab batches
    -- All other rooms are used for theory classes
);

CREATE TABLE IF NOT EXISTS subjects (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    name           VARCHAR(100) NOT NULL,   -- suffix _lab for lab subjects
    teacher_id     INT NOT NULL,
    hours_per_week INT DEFAULT 3,           -- for theory slots; labs always = 2 periods
    FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS timetables (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    day        VARCHAR(10) NOT NULL,
    period     VARCHAR(20) NOT NULL,
    subject_id INT NOT NULL,
    teacher_id INT NOT NULL,
    room_id    INT NOT NULL,
    batch      VARCHAR(5)  DEFAULT '',      -- 'A1', 'A2' for lab rows; '' for theory
    FOREIGN KEY (subject_id) REFERENCES subjects(id)  ON DELETE CASCADE,
    FOREIGN KEY (teacher_id) REFERENCES teachers(id)  ON DELETE CASCADE,
    FOREIGN KEY (room_id)    REFERENCES rooms(id)     ON DELETE CASCADE
);

-- ─── SEED DATA ────────────────────────────────────────────────────

INSERT INTO users (username, password, role) VALUES
('admin', 'admin123', 'admin');

-- Teachers
INSERT INTO teachers (name) VALUES
('Mrs. NehaGouri'),      -- 1  ADA
('Dr. Rajini'),          -- 2  DBMS
('Mrs. Reva'),           -- 3  AIML
('Mrs. Hema'),           -- 4  MC / MC_lab
('Dr. Ravindra'),        -- 5  Discrete Maths
('Dr. Chandramouli');    -- 6  UHV

-- Rooms
-- Theory rooms (no "lab" in name)
INSERT INTO rooms (name, capacity) VALUES
('ASF013', 60),
('ASF014', 60);

-- Lab rooms (must contain "lab" in name — algorithm picks these for _lab subjects)
INSERT INTO rooms (name, capacity) VALUES
('Lab 1', 30),
('Lab 2', 30);

-- Subjects
-- Theory only (no _lab suffix)
INSERT INTO subjects (name, teacher_id, hours_per_week) VALUES
('ADA',            1, 3),
('DBMS',           2, 3),
('AIML',           3, 3),
('MC',             4, 3),
('Discrete Maths', 5, 3),
('UHV',            6, 2);

-- Lab subjects (_lab suffix — each gets ONE 2-period block per week, split A1/A2)
INSERT INTO subjects (name, teacher_id, hours_per_week) VALUES
('ADA_lab',  1, 2),    -- ADA Lab
('DBMS_lab', 2, 2);    -- DBMS Lab  (AEC subject)