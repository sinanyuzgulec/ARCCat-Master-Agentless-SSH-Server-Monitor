# 🚀 ARCCat Master: Agentless SSH Server Monitor

**ARCCat Master**, Linux sunucularınızın sağlık durumunu ve performans metriklerini, hedef sunuculara herhangi bir ajan (agent) kurmadan, sadece standart SSH protokolü üzerinden anlık olarak takip etmenizi sağlayan yüksek performanslı, Python/Dash tabanlı bir izleme panelidir.

![Python](https://img.shields.io/badge/Python-3.8+-blue?style=for-the-badge&logo=python)
![Dash](https://img.shields.io/badge/Dash-2.14-007aff?style=for-the-badge&logo=plotly)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![UI](https://img.shields.io/badge/UI-Dark--Mode-black?style=for-the-badge)

---

## ✨ Öne Çıkan Özellikler

* **Ajan (Agentless) Olmayan Mimari:** Sunucularda Python veya ek bir paket gerektirmez; standart bir SSH erişimi yeterlidir.
* **Paralel İzleme Motoru:** `ThreadPoolExecutor` kullanarak tüm sunucuları eş zamanlı sorgular ve darboğazı önler.
* **Apple-Style Modern UI:** `dash-bootstrap-components` (DARKLY) ile güçlendirilmiş, yüksek okunabilirlik sunan karanlık mod odaklı tasarım.
* **Anlık Telemetri Verileri:**
    * **CPU & Sıcaklık:** Çekirdek yükü ve `/sys/class/thermal` üzerinden sıcaklık takibi.
    * **Bellek Yönetimi:** Detaylı RAM ve Swap kullanımı.
    * **Disk Analizi:** Bağlı disklerin doluluk oranları (GB bazında).
    * **Ağ Trafiği:** Anlık download/upload hızları ve toplam veri transferi hesaplaması.
* **Akıllı Alarm Sistemi:** Windows bildirimleri (`win10toast`) entegrasyonu ile CPU, RAM ve "Offline" durumları için eşik değer tabanlı uyarılar.
* **Dinamik Yönetim:** Uygulama içerisinden sunucu ekleme/silme ve alarm eşiklerini anlık güncelleme. (Persistence: `servers.json`).

---

## 🛠️ Teknik Mimari

Proje, düşük kaynak tüketimi ve yüksek performans için şu teknolojileri kullanır:

| Bileşen | Teknoloji | Açıklama |
| :--- | :--- | :--- |
| **Backend** | Python 3.8+ | Ana mantık ve SSH yönetimi. |
| **SSH Library** | Paramiko | Ed25519 ve RSA anahtar desteği ile güvenli bağlantı. |
| **Dashboard** | Plotly Dash | Reaktif ve veri odaklı web arayüzü. |
| **Concurrency** | ThreadPool | Multi-threading ile eş zamanlı sunucu sorgulama. |
| **Persistence** | JSON | Konfigürasyon ve sunucu listesi saklama. |

---

## ⚠️ Güvenlik Notu (Security Note)

Mevcut implementasyonda SSH bağlantıları için `paramiko.AutoAddPolicy()` kullanılmaktadır.
* **Risk:** Bu politika, SSH anahtarı bilinmeyen sunucuları otomatik olarak güvenilir kabul eder.
* **Etki:** Yerel ağ veya test ortamları için pratik olsa da, dış ağa açık (production) ortamlarda **Man-in-the-Middle (MitM)** saldırılarına karşı zafiyet oluşturabilir. 
* **Öneri:** Kritik sistemlerde host key doğrulaması yapılması veya bilinen anahtarların `known_hosts` dosyasına önceden eklenmesi tavsiye edilir.

---

## 🚀 Hızlı Başlangıç

### 1. Gereksinimlerin Yüklenmesi
Sisteminize gerekli kütüphaneleri yükleyin:

```bash
pip install -r requirements.txt
