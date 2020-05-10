#! /bin/bash

if [ ! -d ~/jars ]; then
  mkdir -p ~/jars
  echo "Fetching jars"
  wget https://github.com/slarse/sootdiff/releases/download/spork-experiment/sootdiff-1.0-jar-with-dependencies.jar -o ~/jars/sootdiff.jar
  wget https://github.com/slarse/duplicate-checkcast-remover/releases/download/v1.0.0/duplicate-checkcast-remover-1.0.0-jar-with-dependencies.jar -o ~/jars/duplicate-checkcast-remover.jar
  wget https://github.com/slarse/pkgextractor/releases/download/v1.0.0/pkgextractor-1.0.0-jar-with-dependencies.jar -o ~/jars/pkgextractor.jar
fi

echo "Setting JAVA_HOME"
export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
echo $JAVA_HOME

echo "Compiling spork"
mvn clean compile package -DskipTests
spork_jar_path="$PWD/$(ls target/spork*.jar)"

echo "Creating spork executable"
echo "#! /bin/bash" > spork
echo "java -jar $spork_jar_path" '$@' >> spork
chmod 700 spork
mv spork ~/

cp "$TRAVIS_BUILD_DIR/.travis/{sootdiff,pkgextractor,duplicate-checkcast-remover}" ~/

cat "$TRAVIS_BUILD_DIR/.travis/gitconfig" >> ~/.gitconfig

git checkout benchmark

cd scripts || exit

python3 -m pip install -r requirements.txt
python3 -m benchmark.cli run-git-merges \
  -r spoon \
  -g inria \
  --merge-commits buildable_spoon_merges.txt \
  --merge-drivers spork \
  --eval-dir evaluation-directory \
  --output results.csv

cat results.csv

diff expected_build_results.csv results.csv
exit $?
