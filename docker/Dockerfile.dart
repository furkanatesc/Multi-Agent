# Runtime image for analyzing/testing generated Flutter / Dart projects.
#
# Uses the Cirrus Labs Flutter image, which bundles both the Flutter SDK and the
# Dart toolchain (so `flutter analyze` / `flutter test` and plain `dart` all
# work). The generated project's files are streamed in at runtime; the inner loop
# runs `flutter pub get` + analyze + test.
#
# Includes coreutils `timeout`, which DockerRunner uses to bound each command.
FROM ghcr.io/cirruslabs/flutter:stable

WORKDIR /app

ENV CI=true

# Image is generic; the project + commands arrive at runtime.
CMD ["sleep", "infinity"]
