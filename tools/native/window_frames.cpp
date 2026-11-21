// External capture of one explicitly owned Windows application window.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>

#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
namespace fs = std::filesystem;
using namespace winrt;
using namespace winrt::Windows::Graphics::Capture;
using winrt::Windows::Graphics::DirectX::DirectXPixelFormat;
using winrt::Windows::Graphics::DirectX::Direct3D11::IDirect3DDevice;
using ::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess;
using Tick = std::int64_t;

struct Rect { std::uint32_t x, y, width, height; };
struct Options {
    DWORD pid;
    HWND hwnd;
    fs::path image, output;
    std::uint32_t width, height, duration_ms, max_frames;
    Rect crop;
};

constexpr auto usage =
    "window_frames --pid PID --image ABSOLUTE_EXE --out NEW_DIRECTORY "
    "--size WIDTHxHEIGHT --duration-ms N --max-frames N [--hwnd 0xHEX] [--crop X,Y,W,H]";

std::uint64_t number(std::wstring_view text, std::uint64_t max, int base = 10) {
    if (text.empty() || text.find_first_not_of(base == 10 ? L"0123456789" : L"0123456789ABCDEFabcdef") != text.npos)
        throw std::invalid_argument("Expected an unsigned integer");
    const auto value = std::stoull(std::wstring(text), nullptr, base);
    if (value > max) throw std::invalid_argument("Number exceeds its bound");
    return value;
}

template <std::size_t N>
std::array<std::uint32_t, N> components(std::wstring_view text, wchar_t separator) {
    std::array<std::uint32_t, N> values{};
    for (std::size_t i = 0; i < N; ++i) {
        const auto end = text.find(separator);
        if ((end == text.npos) != (i == N - 1)) throw std::invalid_argument("Wrong number of dimensions");
        values[i] = static_cast<std::uint32_t>(number(text.substr(0, end), 16384));
        if (end != text.npos) text.remove_prefix(end + 1);
    }
    return values;
}

Options parse(int argc, wchar_t** argv) {
    std::map<std::wstring_view, std::wstring_view> args;
    if (argc % 2 == 0) throw std::invalid_argument(usage);
    for (int i = 1; i < argc; i += 2)
        if (!args.emplace(argv[i], argv[i + 1]).second) throw std::invalid_argument("Duplicate option");
    const auto take = [&](std::wstring_view key) {
        const auto entry = args.find(key);
        if (entry == args.end()) throw std::invalid_argument(usage);
        const auto value = entry->second;
        args.erase(entry);
        return value;
    };
    Options options{};
    options.pid = static_cast<DWORD>(number(take(L"--pid"), std::numeric_limits<DWORD>::max()));
    options.image = fs::path(take(L"--image")).lexically_normal();
    options.output = fs::path(take(L"--out")).lexically_normal();
    const auto size = components<2>(take(L"--size"), L'x');
    options.width = size[0];
    options.height = size[1];
    options.duration_ms = static_cast<std::uint32_t>(number(take(L"--duration-ms"), 30000));
    options.max_frames = static_cast<std::uint32_t>(number(take(L"--max-frames"), 600));
    options.crop = {0, 0, options.width, options.height};
    if (args.contains(L"--crop")) {
        const auto crop = components<4>(take(L"--crop"), L',');
        options.crop = {crop[0], crop[1], crop[2], crop[3]};
    }
    if (args.contains(L"--hwnd")) {
        const auto value = take(L"--hwnd");
        if (!value.starts_with(L"0x")) throw std::invalid_argument("--hwnd must be hexadecimal with a 0x prefix");
        const auto hwnd = number(value.substr(2), std::numeric_limits<std::uintptr_t>::max(), 16);
        if (!hwnd) throw std::invalid_argument("Null HWND");
        options.hwnd = reinterpret_cast<HWND>(static_cast<std::uintptr_t>(hwnd));
    }
    const auto [x, y, width, height] = options.crop;
    if (!args.empty() || !options.pid || !options.image.is_absolute() || !options.output.is_absolute()
        || !options.duration_ms || !options.max_frames || !width || !height
        || x + width > options.width || y + height > options.height
        || std::uint64_t(width) * height * 4 * options.max_frames > 2ull * 1024 * 1024 * 1024)
        throw std::invalid_argument("Invalid bounds, relative path or unknown option");
    return options;
}

bool owns_window(HWND window, DWORD pid) {
    DWORD actual = 0;
    return window && GetWindowThreadProcessId(window, &actual) && actual == pid
        && GetAncestor(window, GA_ROOT) == window && IsWindowVisible(window) && !IsIconic(window);
}

HWND choose_window(const Options& options) {
    if (options.hwnd) {
        if (!owns_window(options.hwnd, options.pid)) throw std::runtime_error("Specified HWND is not an eligible window for the PID");
        return options.hwnd;
    }
    struct Selection { DWORD pid; HWND window; bool ambiguous; } selection{options.pid, nullptr, false};
    EnumWindows([](HWND window, LPARAM opaque) -> BOOL {
        auto& found = *reinterpret_cast<Selection*>(opaque);
        if (!owns_window(window, found.pid)) return TRUE;
        if (found.window) {
            found.ambiguous = true;
            return FALSE;
        }
        found.window = window;
        return TRUE;
    }, reinterpret_cast<LPARAM>(&selection));
    if (!selection.window || selection.ambiguous)
        throw std::runtime_error("Expected exactly one visible top-level PID window. Specify --hwnd if ambiguous");
    return selection.window;
}

Tick clock_ticks() {
    LARGE_INTEGER result{};
    if (!QueryPerformanceCounter(&result)) throw std::runtime_error("QueryPerformanceCounter failed");
    return result.QuadPart;
}

struct Frame { Tick source_time, receipt_qpc; };
struct Capture {
    Tick frequency = 0, start = 0, end = 0;
    std::int32_t source_width = 0, source_height = 0;
    std::vector<Frame> frames;
    const char* completion = nullptr;
};

void atomic_json(const fs::path& folder, const wchar_t* name, auto write) {
    const auto temporary = folder / (std::wstring(name) + L".writing");
    std::ofstream file(temporary, std::ios::binary);
    write(file);
    file.close();
    if (!file) throw std::runtime_error("Could not write capture metadata");
    fs::rename(temporary, folder / name);
}

void identity_fields(std::ostream& out, const Options& options) {
    out << "\"pid\":" << options.pid << ",\"hwnd\":" << reinterpret_cast<std::uintptr_t>(options.hwnd);
}

void capture_window(const Options& options, HANDLE process, Capture& capture) {
    if (!GraphicsCaptureSession::IsSupported()) throw std::runtime_error("Windows Graphics Capture is unavailable");
    const auto factory = get_activation_factory<GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
    GraphicsCaptureItem item{nullptr};
    check_hresult(factory->CreateForWindow(options.hwnd, guid_of<GraphicsCaptureItem>(), put_abi(item)));
    const auto source = item.Size();
    capture.source_width = source.Width;
    capture.source_height = source.Height;
    if (source.Width != static_cast<std::int32_t>(options.width) || source.Height != static_cast<std::int32_t>(options.height))
        throw std::runtime_error("Window content size differs from --size: " + std::to_string(source.Width) + "x" + std::to_string(source.Height));

    com_ptr<ID3D11Device> device;
    com_ptr<ID3D11DeviceContext> context;
    check_hresult(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                                  nullptr, 0, D3D11_SDK_VERSION, device.put(), nullptr, context.put()));
    const auto dxgi = device.as<IDXGIDevice>();
    com_ptr<::IInspectable> inspectable;
    check_hresult(CreateDirect3D11DeviceFromDXGIDevice(dxgi.get(), inspectable.put()));
    auto gpu = inspectable.as<IDirect3DDevice>();
    auto pool = Direct3D11CaptureFramePool::CreateFreeThreaded(gpu, DirectXPixelFormat::B8G8R8A8UIntNormalized, 3, source);
    auto session = pool.CreateCaptureSession(item);
    session.IsCursorCaptureEnabled(false);

    const auto [x, y, width, height] = options.crop;
    D3D11_TEXTURE2D_DESC description{};
    description.Width = width;
    description.Height = height;
    description.MipLevels = 1;
    description.ArraySize = 1;
    description.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    description.SampleDesc.Count = 1;
    description.Usage = D3D11_USAGE_STAGING;
    description.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    com_ptr<ID3D11Texture2D> staging;
    check_hresult(device->CreateTexture2D(&description, nullptr, staging.put()));
    const D3D11_BOX box{x, y, 0, x + width, y + height, 1};
    std::ofstream raw(options.output / L"frames.bgra", std::ios::binary);
    if (!raw) throw std::runtime_error("Could not open frame stream");
    capture.frames.reserve(options.max_frames);

    LARGE_INTEGER frequency{};
    if (!QueryPerformanceFrequency(&frequency) || frequency.QuadPart <= 0)
        throw std::runtime_error("QueryPerformanceFrequency failed");
    capture.frequency = frequency.QuadPart;
    capture.start = clock_ticks();
    const auto deadline = capture.start + capture.frequency * options.duration_ms / 1000;
    session.StartCapture();
    while (capture.frames.size() < options.max_frames && clock_ticks() < deadline) {
        if (WaitForSingleObject(process, 0) != WAIT_TIMEOUT || !owns_window(options.hwnd, options.pid))
            throw std::runtime_error("The captured process or window ceased to match");
        const auto frame = pool.TryGetNextFrame();
        if (!frame) { Sleep(1); continue; }
        const Frame evidence{frame.SystemRelativeTime().count(), clock_ticks()};
        const auto size = frame.ContentSize();
        if (size.Width != source.Width || size.Height != source.Height || evidence.source_time <= 0)
            throw std::runtime_error("A captured frame has an unexpected size or source time");
        const auto surface = frame.Surface().as<IDirect3DDxgiInterfaceAccess>();
        com_ptr<ID3D11Texture2D> texture;
        check_hresult(surface->GetInterface(guid_of<ID3D11Texture2D>(), texture.put_void()));
        context->CopySubresourceRegion(staging.get(), 0, 0, 0, 0, texture.get(), 0, &box);
        context->Flush();
        D3D11_MAPPED_SUBRESOURCE mapped{};
        auto result = context->Map(staging.get(), 0, D3D11_MAP_READ, D3D11_MAP_FLAG_DO_NOT_WAIT, &mapped);
        while (result == DXGI_ERROR_WAS_STILL_DRAWING && clock_ticks() < deadline) {
            Sleep(1);
            result = context->Map(staging.get(), 0, D3D11_MAP_READ, D3D11_MAP_FLAG_DO_NOT_WAIT, &mapped);
        }
        check_hresult(result);
        const auto* data = static_cast<const char*>(mapped.pData);
        for (std::uint32_t row = 0; row < height; ++row)
            raw.write(data + std::size_t(row) * mapped.RowPitch, std::streamsize(width) * 4);
        context->Unmap(staging.get(), 0);
        if (!raw) throw std::runtime_error("Could not write complete frame");
        capture.frames.push_back(evidence);
        if (capture.frames.size() == 1) {
            raw.flush();
            if (!raw) throw std::runtime_error("Could not flush the first frame");
            atomic_json(options.output, L"ready.json", [&](std::ostream& out) {
                out << "{\"schemaVersion\":1,";
                identity_fields(out, options);
                out << ",\"captureStartQpc\":" << capture.start << ",\"qpcFrequency\":" << capture.frequency
                    << ",\"firstSystemRelativeTime100ns\":" << evidence.source_time << "}\n";
            });
        }
    }
    session.Close();
    capture.end = clock_ticks();
    pool.Close();
    raw.close();
    if (!raw || capture.frames.empty()) throw std::runtime_error("Capture produced no complete frame stream");
    capture.completion = capture.frames.size() == options.max_frames ? "frame-limit" : "duration-limit";
}

void write_capture(const Options& options, const fs::path& actual_image, std::uint64_t creation, const Capture& capture) {
    const auto image = actual_image.u8string();
    const std::string utf8(reinterpret_cast<const char*>(image.data()), image.size());
    const auto [x, y, width, height] = options.crop;
    atomic_json(options.output, L"capture.json", [&](std::ostream& out) {
        out << "{\"schemaVersion\":1,\"status\":\"" << (capture.completion ? "completed" : "failed")
            << "\",\"endReason\":\"" << (capture.completion ? capture.completion : "failed") << "\",";
        identity_fields(out, options);
        out << ",\"processImage\":" << std::quoted(utf8) << ",\"processCreationTimeFiletime\":" << creation
            << ",\"captureStartQpc\":" << capture.start << ",\"captureEndQpc\":" << capture.end
            << ",\"qpcFrequency\":" << capture.frequency << ",\"sourceSize\":{\"width\":" << capture.source_width
            << ",\"height\":" << capture.source_height << "},\"crop\":{\"x\":" << x << ",\"y\":" << y
            << ",\"width\":" << width << ",\"height\":" << height
            << "},\"pixelFormat\":\"B8G8R8A8_UNORM\",\"rowStrideBytes\":" << std::uint64_t(width) * 4 << ",\"frames\":[";
        for (std::size_t i = 0; i < capture.frames.size(); ++i) {
            const auto& frame = capture.frames[i];
            out << (i == 0 ? "\n" : ",\n") << "{\"index\":" << i << ",\"offsetBytes\":" << i * std::uint64_t(width) * height * 4
                << ",\"systemRelativeTime100ns\":" << frame.source_time << ",\"receiptQpc\":" << frame.receipt_qpc << '}';
        }
        out << "]}\n";
    });
}
} // namespace

int wmain(int argc, wchar_t** argv) {
    if (argc == 2 && std::wstring_view(argv[1]) == L"--help") { std::cout << usage << '\n'; return 0; }
    try {
        auto options = parse(argc, argv);
        const handle process{OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, options.pid)};
        if (!process) throw std::runtime_error("Could not open the specified process");
        std::wstring image(32768, L'\0');
        DWORD image_length = static_cast<DWORD>(image.size());
        FILETIME creation{}, exit_time{}, kernel{}, user{};
        if (!QueryFullProcessImageNameW(process.get(), 0, image.data(), &image_length)
            || !GetProcessTimes(process.get(), &creation, &exit_time, &kernel, &user))
            throw std::runtime_error("Could not read the specified process identity");
        image.resize(image_length);
        const fs::path actual_image(image);
        if (_wcsicmp(actual_image.lexically_normal().c_str(), options.image.c_str()) != 0)
            throw std::runtime_error("The PID image does not match --image");
        options.hwnd = choose_window(options);
        init_apartment(apartment_type::multi_threaded);
        if (!fs::create_directory(options.output)) throw std::runtime_error("Output directory already exists");
        Capture capture;
        int status = 0;
        try { capture_window(options, process.get(), capture); }
        catch (const hresult_error& error) { std::cerr << to_string(error.message()) << '\n'; status = 1; }
        catch (const std::exception& error) { std::cerr << error.what() << '\n'; status = 1; }
        if (capture.start && !capture.end) capture.end = clock_ticks();
        write_capture(options, actual_image, (std::uint64_t(creation.dwHighDateTime) << 32) | creation.dwLowDateTime, capture);
        return status;
    } catch (const hresult_error& error) { std::cerr << to_string(error.message()) << '\n'; }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; }
    return 1;
}
